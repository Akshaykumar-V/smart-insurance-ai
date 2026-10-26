"""Opt-in integration gate. Requires a migrated disposable Supabase project and two users."""

import os
from uuid import uuid4

import httpx
import pytest
from conftest import make_pdf
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_LIVE") != "1",
    reason="Live Supabase requires explicit RUN_SUPABASE_LIVE=1 opt-in",
)
@pytest.mark.parametrize("reverse_users", [False, True], ids=["owner-a", "owner-b"])
def test_live_upload_pages_and_cross_user_isolation(reverse_users):
    settings = Settings()
    if not all(
        (
            settings.supabase_url,
            settings.supabase_publishable_key,
            os.getenv("TEST_SUPABASE_TOKEN_A"),
            os.getenv("TEST_SUPABASE_TOKEN_B"),
        )
    ):
        pytest.fail(
            "Live opt-in requires project URL, public key and two user tokens", pytrace=False
        )
    token_a, token_b = os.environ["TEST_SUPABASE_TOKEN_A"], os.environ["TEST_SUPABASE_TOKEN_B"]
    if reverse_users:
        token_a, token_b = token_b, token_a
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    rest_headers = {**headers_a, "apikey": settings.supabase_publishable_key}
    ids = None
    path = None
    paths = []
    with httpx.Client(base_url=settings.supabase_url, headers=rest_headers, timeout=20) as rest:
        auth_a = rest.get("/auth/v1/user")
        auth_b = rest.get("/auth/v1/user", headers=headers_b)
        assert auth_a.status_code == auth_b.status_code == 200, "Refresh both test-user sessions"
        owner_a = auth_a.json()["id"]
        owner_b = auth_b.json()["id"]
        assert owner_a != owner_b, "Use two distinct test users"
        try:
            with TestClient(create_app(settings)) as client:
                for auth in ({}, {"Authorization": "Bearer invalid-token"}):
                    assert client.get(f"/api/v1/jobs/{uuid4()}", headers=auth).status_code == 401
                    denied = client.post(
                        "/api/v1/policies/upload",
                        headers=auth,
                        files={"file": ("fictional.pdf", make_pdf(), "application/pdf")},
                    )
                    assert denied.status_code == 401
                response = client.post(
                    "/api/v1/policies/upload",
                    headers=headers_a,
                    files={
                        "file": (
                            "fictional-test.pdf",
                            make_pdf(("Fictional test", "")),
                            "application/pdf",
                        )
                    },
                )
                assert response.status_code == 202
                ids = response.json()
                path = f"{owner_a}/{ids['policy_id']}/{ids['document_id']}.pdf"
                paths.append(path)
                job = client.get(f"/api/v1/jobs/{ids['job_id']}", headers=headers_a)
                assert job.status_code == 200
                assert job.json()["status"] == "needs_review"
                assert job.json()["stage"] == "extracting"
                assert job.json()["error"] is None
                assert "AI analysis is not implemented" in job.json()["message"]
                own_attach = client.post(
                    "/api/v1/policies/upload",
                    headers=headers_a,
                    data={"policy_id": ids["policy_id"], "document_type_hint": "policy_schedule"},
                    files={"file": ("fictional-schedule.pdf", make_pdf(), "application/pdf")},
                )
                assert own_attach.status_code == 202
                attached = own_attach.json()
                paths.append(f"{owner_a}/{ids['policy_id']}/{attached['document_id']}.pdf")
                assert attached["policy_id"] == ids["policy_id"]
                assert attached["document_id"] != ids["document_id"]
                assert (
                    client.get(f"/api/v1/jobs/{ids['job_id']}", headers=headers_b).status_code
                    == 404
                )
                attach = client.post(
                    "/api/v1/policies/upload",
                    headers=headers_b,
                    data={"policy_id": ids["policy_id"]},
                    files={"file": ("fictional.pdf", make_pdf(), "application/pdf")},
                )
                assert attach.status_code == 404
            policy = rest.get("/rest/v1/policies", params={"id": f"eq.{ids['policy_id']}"})
            assert policy.status_code == 200
            assert len(policy.json()) == 1
            for field in ("sum_insured_paise", "policyholder_name", "start_date", "end_date"):
                assert policy.json()[0][field] is None
            pages = rest.get(
                "/rest/v1/document_pages",
                params={
                    "document_id": f"eq.{ids['document_id']}",
                    "order": "page_number.asc",
                },
            )
            pages.raise_for_status()
            assert [page["page_number"] for page in pages.json()] == [1, 2]
            assert pages.json()[0]["text"] == "Fictional test\n"
            assert pages.json()[1]["text"] == ""
            for table, key, value in [
                ("policies", "id", ids["policy_id"]),
                ("documents", "id", ids["document_id"]),
                ("document_pages", "document_id", ids["document_id"]),
                ("analysis_jobs", "id", ids["job_id"]),
            ]:
                hidden = rest.get(
                    f"/rest/v1/{table}", headers=headers_b, params={key: f"eq.{value}"}
                )
                hidden.raise_for_status()
                assert hidden.json() == []
                # Writes targeting another owner's rows must affect no records.
                changed = rest.patch(
                    f"/rest/v1/{table}",
                    headers={**headers_b, "Prefer": "return=representation"},
                    params={key: f"eq.{value}"},
                    json={"owner_id": owner_b},
                )
                assert changed.status_code == 200
                assert changed.json() == []
                removed = rest.delete(
                    f"/rest/v1/{table}",
                    headers={**headers_b, "Prefer": "return=representation"},
                    params={key: f"eq.{value}"},
                )
                assert removed.status_code == 200
                assert removed.json() == []
            # An owner cannot reassign a row to another user (WITH CHECK).
            reassigned = rest.patch(
                "/rest/v1/policies",
                params={"id": f"eq.{ids['policy_id']}"},
                json={"owner_id": owner_b},
            )
            assert reassigned.status_code in (400, 403, 409)
            # Composite FK must reject a B-owned job referencing A's document/policy.
            forged = rest.post(
                "/rest/v1/analysis_jobs",
                headers=headers_b,
                json={
                    "id": str(uuid4()),
                    "owner_id": owner_b,
                    "policy_id": ids["policy_id"],
                    "document_id": ids["document_id"],
                },
            )
            assert forged.status_code in (403, 409)
            # Probe RPC ownership while transitions are valid, so a terminal-state
            # rejection cannot accidentally masquerade as an ownership check.
            queued_doc, queued_job = str(uuid4()), str(uuid4())
            queued_path = f"{owner_a}/{ids['policy_id']}/{queued_doc}.pdf"
            paths.append(queued_path)
            queued_pdf = rest.post(
                f"/storage/v1/object/policy-documents/{queued_path}",
                headers={"Content-Type": "application/pdf"},
                content=make_pdf(("RPC fixture",)),
            )
            assert queued_pdf.status_code == 200
            queued = rest.post(
                "/rest/v1/rpc/create_pdf_upload",
                json={
                    "p_policy_id": ids["policy_id"],
                    "p_document_id": queued_doc,
                    "p_job_id": queued_job,
                    "p_new_policy": False,
                    "p_name": "rpc-fixture.pdf",
                    "p_hint": "other",
                    "p_path": queued_path,
                    "p_sha256": "0" * 64,
                    "p_page_count": 1,
                },
            )
            assert queued.status_code in (200, 204)
            start_payload = {"p_job_id": queued_job}
            denied_start = rest.post(
                "/rest/v1/rpc/start_pdf_extraction", headers=headers_b, json=start_payload
            )
            assert 400 <= denied_start.status_code < 500
            started = rest.post("/rest/v1/rpc/start_pdf_extraction", json=start_payload)
            assert started.status_code in (200, 204)
            finish_payload = {
                "p_job_id": queued_job,
                "p_pages": [
                    {
                        "page_number": 1,
                        "text": "RPC fixture\n",
                        "extraction_quality": "text_present",
                        "method": "pymupdf",
                    }
                ],
                "p_error_code": None,
                "p_message": "Fictional RPC isolation fixture",
            }
            denied_finish = rest.post(
                "/rest/v1/rpc/finish_pdf_extraction", headers=headers_b, json=finish_payload
            )
            assert 400 <= denied_finish.status_code < 500
            finished = rest.post("/rest/v1/rpc/finish_pdf_extraction", json=finish_payload)
            assert finished.status_code in (200, 204)
            # Cross-user create RPC also fails; no Storage object is needed for this probe.
            forged_doc = str(uuid4())
            rejected = rest.post(
                "/rest/v1/rpc/create_pdf_upload",
                headers=headers_b,
                json={
                    "p_policy_id": ids["policy_id"],
                    "p_document_id": forged_doc,
                    "p_job_id": str(uuid4()),
                    "p_new_policy": False,
                    "p_name": "fictional.pdf",
                    "p_hint": "other",
                    "p_path": f"{owner_b}/{ids['policy_id']}/{forged_doc}.pdf",
                    "p_sha256": "0" * 64,
                    "p_page_count": 1,
                },
            )
            assert 400 <= rejected.status_code < 500
            stored = rest.get(f"/storage/v1/object/authenticated/policy-documents/{path}")
            assert stored.status_code == 200
            blocked = rest.get(
                f"/storage/v1/object/authenticated/policy-documents/{path}", headers=headers_b
            )
            assert blocked.status_code in (400, 403, 404)
            signed = rest.post(
                f"/storage/v1/object/sign/policy-documents/{path}", json={"expiresIn": 60}
            )
            assert signed.status_code == 200
            assert signed.json().get("signedURL")
            denied_sign = rest.post(
                f"/storage/v1/object/sign/policy-documents/{path}",
                headers=headers_b,
                json={"expiresIn": 60},
            )
            assert denied_sign.status_code in (400, 403, 404)
            listed = rest.post(
                "/storage/v1/object/list/policy-documents",
                headers=headers_b,
                json={"prefix": f"{owner_a}/{ids['policy_id']}", "limit": 100},
            )
            assert listed.status_code == 200
            assert listed.json() == []
            attack_path = f"{owner_a}/{ids['policy_id']}/{uuid4()}.pdf"
            paths.append(attack_path)  # Cleanup even if a broken policy permits the attack.
            denied_write = rest.post(
                f"/storage/v1/object/policy-documents/{attack_path}",
                headers={**headers_b, "Content-Type": "application/pdf"},
                content=make_pdf(),
            )
            assert denied_write.status_code in (400, 403)
            denied_delete = rest.request(
                "DELETE",
                "/storage/v1/object/policy-documents",
                headers=headers_b,
                json={"prefixes": [path]},
            )
            assert denied_delete.status_code in (200, 400, 403, 404)
            assert (
                rest.get(f"/storage/v1/object/authenticated/policy-documents/{path}").status_code
                == 200
            )
            public = httpx.get(
                f"{settings.supabase_url}/storage/v1/object/public/policy-documents/{path}",
                timeout=20,
            )
            assert public.status_code in (400, 403, 404)
            with httpx.Client(
                base_url=settings.supabase_url,
                headers={"apikey": settings.supabase_publishable_key},
                timeout=20,
            ) as anon:
                for table in ("policies", "documents", "document_pages", "analysis_jobs"):
                    assert anon.get(f"/rest/v1/{table}").status_code in (401, 403)
                assert anon.get(
                    f"/storage/v1/object/authenticated/policy-documents/{path}"
                ).status_code in (400, 401, 403, 404)
                assert anon.post(
                    "/rest/v1/rpc/start_pdf_extraction", json={"p_job_id": ids["job_id"]}
                ).status_code in (401, 403)
        finally:
            # Remove only the freshly created fictional fixture and its private object.
            if paths:
                cleanup = rest.request(
                    "DELETE", "/storage/v1/object/policy-documents", json={"prefixes": paths}
                )
                cleanup.raise_for_status()
            if ids:
                cleanup = rest.delete("/rest/v1/policies", params={"id": f"eq.{ids['policy_id']}"})
                cleanup.raise_for_status()
                for table, key, value in [
                    ("policies", "id", ids["policy_id"]),
                    ("documents", "policy_id", ids["policy_id"]),
                    ("document_pages", "document_id", ids["document_id"]),
                    ("analysis_jobs", "policy_id", ids["policy_id"]),
                ]:
                    remaining = rest.get(f"/rest/v1/{table}", params={key: f"eq.{value}"})
                    assert remaining.status_code == 200
                    assert remaining.json() == []
