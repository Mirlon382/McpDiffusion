"""The three MELODI tools this brick publishes.

Every tool is a plain function, so none of them carries a registration wrapper; each takes the
service it needs through `Depends`.
"""

from fastmcp import FastMCP

from ..settings import Settings
from .get_observations_tool import get_melodi_observations
from .search_datasets_tool import search_melodi_datasets
from .search_modalities_tool import search_melodi_modalities


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    """Register this brick's three tools.

    `settings` is part of the core's registration contract and stays unused here: which bricks a
    process serves is the process's decision, and this brick always publishes all of its own tools.
    """
    mcp.add_tool(search_melodi_datasets)
    mcp.add_tool(search_melodi_modalities)
    mcp.add_tool(get_melodi_observations)
