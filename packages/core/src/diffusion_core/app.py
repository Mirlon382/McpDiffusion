"""The one application assembly a brick needs: app, middlewares, ASGI app, runner.

Every brick would otherwise copy-paste this block verbatim. The brick contributes only
what is its own: a name, handshake instructions, a lifespan, a `register(mcp, settings)`
callable, and its settings object.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.lifespan import Lifespan
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware

from .client_host import resolve_client_host
from .logging import build_logging_config, configure_logging
from .settings import ServerSettings

logger = logging.getLogger(__name__)


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
    instructions: str,
    lifespan: Lifespan,
    register: Callable[[FastMCP, SettingsT], None],
    settings: SettingsT,
) -> McpApplication[SettingsT]:
    """Build the FastMCP app, register its tools, apply the shared middleware chain, and wrap it as an ASGI app.

    The middleware order is the one the FastMCP docs prescribe and the boot tests assert:
    error handling first so it sees the whole chain, logging last so it records what ran.
    """
    configure_logging(settings.log_level)

    mcp = FastMCP(
        name,
        instructions=instructions,
        # Only AppToolError messages reach the caller; anything else is a bug and is replaced
        # by a generic message.
        mask_error_details=True,
        lifespan=lifespan,
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
    )
