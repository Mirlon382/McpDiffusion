"""Entrypoint: builds the settings, the clients and the MCP application, then serves it over HTTP.

The app itself is assembled by the core's `create_server`: FastMCP instance, the four shared
middlewares, host/origin protection and the uvicorn runner. What stays here is what belongs to
this one process -- its settings, its handshake instructions, and which tools it registers.
"""

from textwrap import dedent

from diffusion_core import create_server

from .lifespan import build_lifespan
from .settings import load_settings
from .tools import register_tools

settings = load_settings()

# Sent to the client in the handshake. Only what belongs to no single tool: which tool to call, and when,
# is in the tool descriptions, where it reaches the model even when a client drops these instructions.

# language=Markdown
INSTRUCTIONS = dedent("""
    This server exposes INSEE (French national statistics) data through three sources:

    - insee.fr -- publications, rapid releases and headline indicators
    - MELODI -- the dataset catalogue and the observations themselves
    - RMES -- statistical metadata: definitions and nomenclatures. It holds no figures.

    Rules that apply to every tool:

    - Never guess a dataset id, a modality code, a document URL or a graph URI. Each is opaque and must come
      from a discovery call first.
    - The data is French. Search with French keywords and rich synonyms.
    - An empty result is a valid answer, not a failure. It usually means the filters were too narrow.
    - A tool description may point you at a tool from another source. Only the tools in your tool list exist
      here; if a description names one you do not have, ignore it and use what you have.
""").strip()

application = create_server(
    name="INSEE-mcp-diffusion",
    instructions=INSTRUCTIONS,
    lifespan=build_lifespan(settings),
    register=register_tools,
    settings=settings,
)

# The names an ASGI server and an in-memory Client connect to: `app` serves HTTP, `mcp` is the
# FastMCP application with the whole middleware chain and the twelve registered tools behind it.
app = application.app
mcp = application.mcp

if __name__ == "__main__":
    application.run()
