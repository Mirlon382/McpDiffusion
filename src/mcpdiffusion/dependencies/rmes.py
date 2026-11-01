"""The RMES service a tool can be handed."""

from typing import cast

from fastmcp import Context
from fastmcp.dependencies import CurrentContext

from ..lifespan.rmes import RmesContext
from ..services.rmes.graph_store_service import RmesGraphStoreService


def get_rmes_graph_store_service(ctx: Context = CurrentContext()) -> RmesGraphStoreService:
    """Return the RMES graph store service built at startup."""
    return cast(RmesContext, ctx.lifespan_context)["rmes_graph_store_service"]
