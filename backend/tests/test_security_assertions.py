"""Offline regression of the live security oracle; these do not prove deployed RLS."""

import httpx
import pytest
from test_supabase_live import assert_no_private_rows, assert_write_denied

from app.diagnostics import Operation


@pytest.mark.parametrize("actor", ["anonymous", "cross-user"])
@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
@pytest.mark.parametrize("status", [200, 401, 403])
def test_hidden_rows_accept_empty_or_denied(actor, method, status):
    response = httpx.Response(
        status, json=[], request=httpx.Request(method, "https://example.test")
    )
    assert_no_private_rows(response)


@pytest.mark.parametrize("actor", ["anonymous", "cross-user"])
@pytest.mark.parametrize(
    "body", [[{"id": "PRIVATE_SENTINEL"}], {"private": "PRIVATE_SENTINEL"}, None]
)
def test_exposure_or_wrong_shape_fails_without_contents(actor, body):
    with pytest.raises(pytest.fail.Exception) as error:
        assert_no_private_rows(httpx.Response(200, json=body))
    assert "PRIVATE_SENTINEL" not in str(error.value)


@pytest.mark.parametrize("status", [204, 302, 400, 404, 409, 500])
def test_unexpected_read_or_update_status_is_not_security_success(status):
    with pytest.raises(pytest.fail.Exception):
        assert_no_private_rows(httpx.Response(status, json=[]))


def test_invalid_json_fails_without_contents():
    with pytest.raises(pytest.fail.Exception) as error:
        assert_no_private_rows(httpx.Response(200, content=b"PRIVATE_SENTINEL"))
    assert "PRIVATE_SENTINEL" not in str(error.value)


@pytest.mark.parametrize("status", [401, 403])
def test_insert_and_rpc_permission_denials(status):
    assert_write_denied(httpx.Response(status))


@pytest.mark.parametrize("status", [200, 201, 204, 400, 404, 409, 500])
def test_insert_and_rpc_success_or_other_errors_fail(status):
    with pytest.raises(pytest.fail.Exception):
        assert_write_denied(httpx.Response(status, json=[]))


@pytest.mark.parametrize("operation", [Operation.START_EXTRACTION, Operation.FINISH_EXTRACTION])
@pytest.mark.parametrize("code", ["PT404", "PGRST202", "P0002", "PRIVATE_SENTINEL"])
def test_rpc_body_or_cache_errors_are_not_permission_denials(operation, code):
    response = httpx.Response(404, json={"code": code, "message": "PRIVATE_SENTINEL"})
    with pytest.raises(pytest.fail.Exception) as error:
        assert_write_denied(response, operation)
    message = str(error.value)
    assert f"operation={operation.value}" in message
    assert "HTTP 404" in message
    assert "PRIVATE_SENTINEL" not in message
    assert f"code={code if code != 'PRIVATE_SENTINEL' else 'unknown'}" in message


def test_insert_failure_has_safe_operation_label():
    with pytest.raises(pytest.fail.Exception) as error:
        assert_write_denied(httpx.Response(500, content=b"PRIVATE_SENTINEL"))
    assert "operation=anonymous_policy_insert" in str(error.value)
    assert "code=unknown" in str(error.value)
    assert "PRIVATE_SENTINEL" not in str(error.value)
