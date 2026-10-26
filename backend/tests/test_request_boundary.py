import asyncio
import json

from app.main import RequestBoundary


def test_chunked_request_cannot_bypass_limit_without_content_length():
    async def run():
        messages = []
        events = iter(
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"5678", "more_body": False},
            ]
        )

        async def receive():
            return next(events)

        async def send(message):
            messages.append(message)

        async def never_called(*args):
            raise AssertionError("Oversized request must not reach the application")

        await RequestBoundary(never_called, max_bytes=6)(
            {"type": "http", "headers": [], "method": "POST"},
            receive,
            send,
        )
        assert messages[0]["status"] == 413
        assert json.loads(messages[1]["body"])["error"]["code"] == "FILE_TOO_LARGE"

    asyncio.run(run())
