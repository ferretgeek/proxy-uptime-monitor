from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ASGIMessage = dict[str, Any]
Receive = Callable[[], Awaitable[ASGIMessage]]
Send = Callable[[ASGIMessage], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Reject oversized state-changing requests before framework parsing."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @staticmethod
    def _limit(scope: dict[str, Any]) -> int | None:
        if scope.get("type") != "http":
            return None
        method = str(scope.get("method", "GET")).upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        return 4096 if scope.get("path") == "/api/login" else 1024 * 1024

    async def __call__(
        self, scope: dict[str, Any], receive: Receive, send: Send
    ) -> None:
        limit = self._limit(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(raw_length)
            except ValueError:
                await self._reject(send, 400, b'{"detail":"Content-Length invalid"}')
                return
            if declared_length < 0:
                await self._reject(send, 400, b'{"detail":"Content-Length invalid"}')
                return
            if declared_length > limit:
                await self._reject(send, 413, b'{"detail":"Request body too large"}')
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > limit:
                await self._reject(send, 413, b'{"detail":"Request body too large"}')
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay_receive() -> ASGIMessage:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(send: Send, status: int, body: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
