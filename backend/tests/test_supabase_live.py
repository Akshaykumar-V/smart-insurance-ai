"""Opt-in integration gate. Requires a migrated disposable Supabase project and two users."""

import os
from uuid import uuid4

import httpx
import pytest
from conftest import make_pdf
from fastapi.testclient import TestClient

from app.config import Settings
from app.diagnostics import Operation, log_upstream_failure, safe_upstream_code
from app.main import create_app
from app.supabase import public_schema_headers


def select_public_schema(request: httpx.Request) -> None:
    # Direct fixture reads/writes and cleanup must use the same schema as the API.
    request.headers.update(public_schema_headers(request.method, request.url.path))


def assert_hidden_job(response: httpx.Response, operation: Operation) -> None:
    # These calls bypass FastAPI/Gateway: explicitly emit the same safe diagnostic.
    if not response.is_success:
        log_upstream_failure(operation, response=response)
    assert response.status_code == 404
    assert safe_upstream_code(response) == "PT404"


def assert_no_private_rows(response: httpx.Response) -> None:
    """Accept privilege denial or RLS-filtered rows; never render response contents."""
    if response.status_code in (401, 403):
        return
    if response.status_code != 200:
        pytest.fail(f"Expected denial or empty rows; HTTP {response.status_code}", pytrace=False)
    try:
        rows = response.json()
    except ValueError:
        pytest.fail("Expected an empty JSON array; invalid JSON", pytrace=False)
    if not isinstance(rows, list) or rows:
        pytest.fail(
            "SECURITY: unexpected rows or response shape; stop and investigate privately",
            pytrace=False,
        )


def assert_write_denied(response: httpx.Response, operation: Operation | None = None) -> None:
    # PT404 proves the RPC body ran; it is NOT an EXECUTE permission denial.
    if response.status_code not in (401, 403):
        label = operation.value if operation is not None else "anonymous_policy_insert"
        pytest.fail(
            f"Expected permission denial; operation={label} "
            f"HTTP {response.status_code} code={safe_upstream_code(response)}",
            pytrace=False,
        )


def extraction_state(rest, job_id, document_id):
    """Inspect only state/physical page numbers, never document text."""
    result = []
    for table, key, value, fields in (
        ("analysis_jobs", "id", job_id, "status,stage,error_code"),
        ("documents", "id", document_id, "processing_status"),
        ("document_pages", "document_id", document_id, "page_number"),
    ):
        response = rest.get(f"/rest/v1/{table}", params={key: f"eq.{value}", "select": fields})
        assert response.status_code == 200
        result.append(response.json())
    return result


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
    anon_policy_id = str(uuid4())
    with httpx.Client(
        base_url=settings.supabase_url,
        headers=rest_headers,
        timeout=20,
        event_hooks={"request": [select_public_schema]},
    ) as rest:
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
                assert_no_private_rows(hidden)
                # Writes targeting another owner's rows must affect no records.
                changed = rest.patch(
                    f"/rest/v1/{table}",
                    headers={**headers_b, "Prefer": "return=representation"},
                    params={key: f"eq.{value}"},
                    json={"owner_id": owner_b},
                )
                assert_no_private_rows(changed)
                removed = rest.delete(
                    f"/rest/v1/{table}",
                    headers={**headers_b, "Prefer": "return=representation"},
                    params={key: f"eq.{value}"},
                )
                assert_no_private_rows(removed)
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
            before_start = extraction_state(rest, queued_job, queued_doc)
            start_payload = {"p_job_id": queued_job}
            denied_start = rest.post(
                "/rest/v1/rpc/start_pdf_extraction", headers=headers_b, json=start_payload
            )
            unchanged = extraction_state(rest, queued_job, queued_doc) == before_start
            assert unchanged, "Denied start must not change job, document or pages"
            assert_hidden_job(denied_start, Operation.START_EXTRACTION)
            missing_start = rest.post(
                "/rest/v1/rpc/start_pdf_extraction",
                headers=headers_b,
                json={"p_job_id": str(uuid4())},
            )
            assert_hidden_job(missing_start, Operation.START_EXTRACTION)
            started = rest.post("/rest/v1/rpc/start_pdf_extraction", json=start_payload)
            assert started.status_code in (200, 204)
            before_finish = extraction_state(rest, queued_job, queued_doc)
            assert before_finish == [
                [{"status": "processing", "stage": "extracting", "error_code": None}],
                [{"processing_status": "extracting"}],
                [],
            ]
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
            unchanged = extraction_state(rest, queued_job, queued_doc) == before_finish
            assert unchanged, "Denied finish must not change job, document or pages"
            assert_hidden_job(denied_finish, Operation.FINISH_EXTRACTION)
            missing_finish = rest.post(
                "/rest/v1/rpc/finish_pdf_extraction",
                headers=headers_b,
                json={**finish_payload, "p_job_id": str(uuid4())},
            )
            assert_hidden_job(missing_finish, Operation.FINISH_EXTRACTION)
            finished = rest.post("/rest/v1/rpc/finish_pdf_extraction", json=finish_payload)
            assert finished.status_code in (200, 204)
            assert extraction_state(rest, queued_job, queued_doc) == [
                [{"status": "needs_review", "stage": "extracting", "error_code": None}],
                [{"processing_status": "extracted"}],
                [{"page_number": 1}],
            ]
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
                event_hooks={"request": [select_public_schema]},
            ) as anon:
                # Check all reads first. Any returned row stops the probes without logging it.
                for table in ("policies", "documents", "document_pages", "analysis_jobs"):
                    assert_no_private_rows(
                        anon.get(f"/rest/v1/{table}", params={"select": "id", "limit": 1})
                    )
                for table, key, value, patch in (
                    ("policies", "id", ids["policy_id"], {"category": "health"}),
                    ("documents", "id", ids["document_id"], {"file_name": "denied.pdf"}),
                    ("document_pages", "document_id", ids["document_id"], {"text": "denied"}),
                    ("analysis_jobs", "id", ids["job_id"], {"message": "denied"}),
                ):
                    params = {key: f"eq.{value}", "order": "id.asc"}
                    before = rest.get(f"/rest/v1/{table}", params=params)
                    assert before.status_code == 200
                    assert bool(before.json()), "Owner fixture must exist before denial probes"
                    for method in ("PATCH", "DELETE"):
                        response = anon.request(
                            method,
                            f"/rest/v1/{table}",
                            params={key: f"eq.{value}"},
                            headers={"Prefer": "return=representation"},
                            **({"json": patch} if method == "PATCH" else {}),
                        )
                        assert_no_private_rows(response)
                        after = rest.get(f"/rest/v1/{table}", params=params)
                        assert after.status_code == 200
                        unchanged = after.json() == before.json()
                        assert unchanged, "SECURITY: denied write changed owner records"
                assert_write_denied(
                    anon.post(
                        "/rest/v1/policies",
                        json={"id": anon_policy_id, "owner_id": owner_a},
                    )
                )
                assert anon.get(
                    f"/storage/v1/object/authenticated/policy-documents/{path}"
                ).status_code in (400, 401, 403, 404)
                for rpc, payload in (
                    ("start_pdf_extraction", {"p_job_id": ids["job_id"]}),
                    (
                        "finish_pdf_extraction",
                        {
                            "p_job_id": ids["job_id"],
                            "p_pages": [],
                            "p_error_code": None,
                            "p_message": "Denied anonymous probe",
                        },
                    ),
                    (
                        "create_pdf_upload",
                        {
                            "p_policy_id": ids["policy_id"],
                            "p_document_id": str(uuid4()),
                            "p_job_id": str(uuid4()),
                            "p_new_policy": False,
                            "p_name": "denied.pdf",
                            "p_hint": "other",
                            "p_path": path,
                            "p_sha256": "0" * 64,
                            "p_page_count": 1,
                        },
                    ),
                ):
                    assert_write_denied(
                        anon.post(f"/rest/v1/rpc/{rpc}", json=payload), Operation(rpc)
                    )
        finally:
            # Track the attempted INSERT too, in case a broken policy permits it.
            rest.delete(
                "/rest/v1/policies", params={"id": f"eq.{anon_policy_id}"}
            ).raise_for_status()
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
