"""The five insee.fr tools this brick publishes.

Every tool is a plain function, so none of them carries a registration wrapper. Those that need a
service take it through `Depends`; `get_insee_homepage` needs none.
"""

from fastmcp import FastMCP

from ..settings import Settings
from .get_document_tool import get_insee_document
from .get_homepage_tool import get_insee_homepage
from .search_chiffrecle_tool import search_insee_chiffrecle
from .search_conjoncture_tool import search_insee_conjoncture
from .search_documents_tool import search_insee_documents


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    """Register this brick's five tools.

    `settings` is part of the core's registration contract and stays unused here: which bricks a
    process serves is the process's decision, and this brick always publishes all of its own tools.
    """
    mcp.add_tool(search_insee_documents)
    mcp.add_tool(get_insee_homepage)
    mcp.add_tool(get_insee_document)
    mcp.add_tool(search_insee_conjoncture)
    mcp.add_tool(search_insee_chiffrecle)
