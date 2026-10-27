"""Credential-handling checks; no real sign-in or subprocess is performed."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from scripts import run_supabase_live as runner


@pytest.mark.parametrize("outcome", ["success", "same_user", "invalid_password"])
def test_runner_passes_tokens_only_to_child_environment(monkeypatch, capsys, outcome):
    settings = Settings(
        _env_file=None,
        supabase_url="https://disposable.invalid",
        supabase_publishable_key="public-test-key",
    )
    monkeypatch.setattr(runner, "Settings", lambda: settings)
    answers = iter(["disposable.invalid", "a@example.invalid", "b@example.invalid"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(runner.getpass, "getpass", lambda prompt: "fixture-password")
    owner_a = str(uuid4())
    owner_b = owner_a if outcome == "same_user" else str(uuid4())
    requests, children = [], []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/auth/v1/token"
        assert request.url.params["grant_type"] == "password"
        assert request.headers["apikey"] == "public-test-key"
        assert json.loads(request.content)["password"] == "fixture-password"
        if outcome == "invalid_password":
            return httpx.Response(400, text="fixture-password secret error body")
        return httpx.Response(
            200,
            json={
                "user": {"id": owner_a if len(requests) == 1 else owner_b},
                "access_token": f"fixture-token-{len(requests)}",
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        runner.httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )

    def child(args, *, env, check):
        children.append(args)
        assert env["RUN_SUPABASE_LIVE"] == "1"
        assert env["TEST_SUPABASE_TOKEN_A"] == "fixture-token-1"
        assert env["TEST_SUPABASE_TOKEN_B"] == "fixture-token-2"
        assert env["AI_EXTRACTION_ENABLED"] == "false"
        assert "--no-showlocals" in args
        assert "--log-cli-level=WARNING" in args
        assert "--log-disable=httpx" in args
        assert "--log-disable=httpcore" in args
        assert "fixture-token" not in str(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", child)
    assert runner.main() == (0 if outcome == "success" else 1)
    assert len(children) == (1 if outcome == "success" else 0)
    output = capsys.readouterr().out
    assert "fixture-password" not in output
    assert "fixture-token" not in output
    assert "secret error body" not in output
