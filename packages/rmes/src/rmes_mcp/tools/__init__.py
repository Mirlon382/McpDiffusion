"""The three RMES tools this brick publishes.

Every tool is a plain function, so none of them carries a registration wrapper; each takes the
service it needs through `Depends`.
"""

from fastmcp import FastMCP

from ..settings import Settings
from .describe_resource_tool import describe_rmes_resource
from .run_sparql_tool import run_rmes_sparql
from .search_graphs_tool import search_rmes_graphs


def register_tools(mcp: FastMCP, settings: Settings) -> None:
    """Register this brick's three tools.

    `settings` is part of the core's registration contract and stays unused here: which bricks a
    process serves is the process's decision, and this brick always publishes all of its own tools.
    """
    mcp.add_tool(search_rmes_graphs)
    mcp.add_tool(describe_rmes_resource)
    mcp.add_tool(run_rmes_sparql)
