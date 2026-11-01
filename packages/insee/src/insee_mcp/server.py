"""Entrypoint: builds the settings, the lifespan and the MCP application, then serves it over HTTP.

The app itself is assembled by the core's `create_server`: FastMCP instance, the four shared
middlewares, host/origin protection and the uvicorn runner. What stays here is what belongs to this
one brick -- its settings, its handshake instructions, and its own tools.
"""

from importlib.metadata import version as package_version

from diffusion_core import create_server

from .instructions import INSTRUCTIONS
from .lifespan import build_health_check, build_lifespan
from .settings import load_settings
from .tools import register_tools

settings = load_settings()

application = create_server(
    name="insee-mcp",
    version=package_version("insee-mcp"),
    instructions=INSTRUCTIONS,
    lifespan=build_lifespan(settings),
    health_check=build_health_check(settings),
    register=register_tools,
    settings=settings,
)

# The names an ASGI server and an in-memory Client connect to: `app` serves HTTP, `mcp` is the
# FastMCP application with the whole middleware chain and this brick's tools behind it.
app = application.app
mcp = application.mcp

if __name__ == "__main__":
    application.run()
