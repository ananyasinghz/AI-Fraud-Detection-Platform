"""Request correlation middleware."""

import re
from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class RequestIdMiddleware:
    """Attach a safe request ID to state and every response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        supplied = request.headers.get(REQUEST_ID_HEADER)
        request_id = supplied if supplied and _SAFE_REQUEST_ID.fullmatch(supplied) else str(uuid4())
        request.state.request_id = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append(
                    (
                        REQUEST_ID_HEADER.lower().encode("latin-1"),
                        request_id.encode("latin-1"),
                    )
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)
