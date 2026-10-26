"""Interactive local runner: tokens/passwords are never printed or written to disk."""

import getpass
import os
import subprocess
import sys
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.config import Settings


def main() -> int:
    settings = Settings()
    project = urlparse(settings.supabase_url)
    if project.scheme != "https" or not project.hostname or not settings.supabase_publishable_key:
        print("Configure the disposable HTTPS Supabase URL and public key in backend/.env first.")
        return 1
    print(f"Target: {project.hostname}. Tests create and delete fictional fixtures.")
    if input("Type the disposable project's hostname to continue: ").strip() != project.hostname:
        print("No live requests made.")
        return 1
    test_env = os.environ.copy()
    owners = []
    try:
        with httpx.Client(base_url=settings.supabase_url, timeout=20) as client:
            for label in ("A", "B"):
                email = input(f"Confirmed test user {label} email: ").strip()
                password = getpass.getpass(f"Test user {label} password: ")
                response = client.post(
                    "/auth/v1/token",
                    params={"grant_type": "password"},
                    headers={"apikey": settings.supabase_publishable_key},
                    json={"email": email, "password": password},
                )
                del password
                if response.status_code != 200:
                    print(f"Sign-in failed for user {label} (HTTP {response.status_code}).")
                    return 1
                session = response.json()
                owners.append(str(UUID(session["user"]["id"])))
                test_env[f"TEST_SUPABASE_TOKEN_{label}"] = session["access_token"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        print("Sign-in unavailable or returned an invalid response; no integration tests run.")
        return 1
    if owners[0] == owners[1]:
        print("Use two distinct test users; no integration tests run.")
        return 1
    test_env["RUN_SUPABASE_LIVE"] = "1"
    test_env["PYTEST_ADDOPTS"] = ""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-m", "live", "--tb=short", "--no-showlocals"],
        env=test_env,
        check=False,
    ).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        raise SystemExit(1) from None
