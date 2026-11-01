"""The one application assembly a brick needs: app, middlewares, ASGI app, runner.

Every brick would otherwise copy-paste this block verbatim. The brick contributes only
what is its own: a name, handshake instructions, a lifespan, a `register(mcp, settings)`
callable, and its settings object.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.lifespan import Lifespan
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .client_host import resolve_client_host
from .logging import build_logging_config, configure_logging
from .settings import ServerSettings

logger = logging.getLogger(__name__)


type BackendStatuses = dict[str, bool]
HealthCheck = Callable[[Any | None], Awaitable[BackendStatuses]]


@dataclass
class McpApplication[SettingsT: ServerSettings]:
    """A fully assembled MCP server, ready to serve or to be tested in memory.

    `.mcp` is the FastMCP app (what an in-memory `Client` connects to), `.app` the ASGI
    application (what uvicorn or any ASGI server serves), `.settings` the object the
    factory read. `run()` is only for the `__main__` entrypoint of a standalone process.
    """

    mcp: FastMCP
    app: StarletteWithLifespan
    settings: SettingsT
    name: str
    version: str
    health_statuses: Callable[[], Awaitable[BackendStatuses]]
    health_payload: Callable[[], Awaitable[dict[str, str | dict[str, str]]]]

    def run(self) -> None:
        """Serve the ASGI app with uvicorn, honouring the trusted proxies for client addresses."""
        uvicorn.run(
            self.app,
            host=self.settings.mcp_host,
            port=self.settings.mcp_port,
            proxy_headers=True,
            forwarded_allow_ips=self.settings.trusted_proxy_hosts,
            log_config=build_logging_config(self.settings.log_level),
        )


def create_server[SettingsT: ServerSettings](
    name: str,
    version: str,
    instructions: str,
    lifespan: Lifespan | None,
    health_check: HealthCheck,
    register: Callable[[FastMCP, SettingsT], None],
    settings: SettingsT,
) -> McpApplication[SettingsT]:
    """Build the FastMCP app, register its tools, apply the shared middleware chain, and wrap it as an ASGI app.

    The middleware order is the one the FastMCP docs prescribe and the boot tests assert:
    error handling first so it sees the whole chain, logging last so it records what ran.
    """
    configure_logging(settings.log_level)

    lifespan_state: dict[str, Any] = {"context": None}

    @asynccontextmanager
    async def tracked_lifespan(server: FastMCP[Any]) -> AsyncIterator[Any]:
        if lifespan is None:
            yield {}
            return

        async with lifespan(server) as context:
            lifespan_state["context"] = context
            try:
                yield context
            finally:
                lifespan_state["context"] = None

    async def health_statuses() -> BackendStatuses:
        """Run the source-specific checks against the active lifespan clients."""
        return await health_check(lifespan_state["context"])

    async def health_payload() -> dict[str, str | dict[str, str]]:
        """Shape a safe, stable response for readiness probes and operators."""
        statuses = await health_statuses()
        backends = {backend: "ready" if ready else "unavailable" for backend, ready in statuses.items()}
        ready = bool(statuses) and all(statuses.values())
        return {
            "name": name,
            "version": version,
            "status": "ready" if ready else "unavailable",
            "backends": backends,
        }

    mcp = FastMCP(
        name,
        instructions=instructions,
        version=version,
        # Only AppToolError messages reach the caller; anything else is a bug and is replaced
        # by a generic message.
        mask_error_details=True,
        lifespan=tracked_lifespan,
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health_route(_request: Request) -> Response:
        payload = await health_payload()
        return JSONResponse(
            payload,
            status_code=200 if payload["status"] == "ready" else 503,
        )

    @mcp.custom_route("/health/live", methods=["GET"])
    async def liveness_route(_request: Request) -> Response:
        return JSONResponse(
            {
                "name": name,
                "version": version,
                "status": "ok",
            },
        )

    register(mcp, settings)

    # Each middleware logs under its own `fastmcp.*` logger; set levels there to tune the output.
    # None of them logs how many results a tool returned. If empty results become hard to diagnose, add an
    # `on_call_tool` middleware that inspects the ToolResult, or have the tool report it with `ctx.info`.
    mcp.add_middleware(
        # include_traceback puts the original cause in the server log, which is the only place it is
        # recoverable. transform_errors would promote our ToolErrors to JSON-RPC protocol errors labelled
        # "Internal error", losing is_error and the message the caller is meant to act on.
        ErrorHandlingMiddleware(
            transform_errors=False,
            include_traceback=True,
        ),
    )
    mcp.add_middleware(
        # The limit is per brick (split decision 3): each process gets its own bucket, keyed per client.
        SlidingWindowRateLimitingMiddleware(
            max_requests=settings.rate_limit_max_requests,
            window_minutes=settings.rate_limit_window_minutes,
            get_client_id=resolve_client_host,
        ),
    )
    mcp.add_middleware(
        TimingMiddleware(),
    )
    mcp.add_middleware(
        LoggingMiddleware(),
    )

    if settings.allowed_hosts == ["*"]:
        logger.warning("allowed_hosts is ['*']. Set ALLOWED_HOSTS before exposing the server publicly.")

    # Enforced rather than "auto": these servers are published under real hostnames, so each
    # should check the one it was reached by instead of leaving the decision to a heuristic.
    app = mcp.http_app(
        host_origin_protection=True,
        allowed_hosts=settings.allowed_hosts,
        allowed_origins=settings.allowed_origins,
    )

    return McpApplication(
        mcp=mcp,
        app=app,
        settings=settings,
        name=name,
        version=version,
        health_statuses=health_statuses,
        health_payload=health_payload,
    )
