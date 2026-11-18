import os
from contextlib import asynccontextmanager

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from asgiref.sync import sync_to_async  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Mount  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402

# Django must be initialized before importing models/the MCP tools.
django_app = get_asgi_application()
from django.conf import settings  # noqa: E402
from django.db import close_old_connections  # noqa: E402
from accounting.auth import DomainError, token_actor  # noqa: E402
from accounting.mcp import http_app, server  # noqa: E402


class MCPAuthentication:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode("latin1")
            try:
                if not auth.startswith("Bearer "):
                    raise DomainError("Bearer-Token erforderlich.", 401)
                def authenticate_token():
                    close_old_connections()
                    try:
                        return token_actor(auth[7:])
                    finally:
                        close_old_connections()
                await sync_to_async(authenticate_token, thread_sensitive=True)()
            except DomainError:
                response = JSONResponse({"error": "Authentifizierung erforderlich."}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(app):
    # Mounts do not start nested ASGI lifespans automatically.
    async with server.session_manager.run():
        yield


application = Starlette(routes=[
    Mount("/mcp", app=MCPAuthentication(http_app)),
    Mount("/static", app=StaticFiles(directory=settings.STATIC_ROOT, check_dir=False)),
    Mount("/", app=django_app),
], lifespan=lifespan)
