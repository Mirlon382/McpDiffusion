"""The Melodi services a tool can be handed."""

from typing import cast

from fastmcp import Context
from fastmcp.dependencies import CurrentContext

from .lifespan import MelodiContext
from .services.api_service import MelodiApiService
from .services.index_service import MelodiIndexService


def get_melodi_index_service(ctx: Context = CurrentContext()) -> MelodiIndexService:
    """Return the Melodi Elasticsearch service built at startup."""
    return cast(MelodiContext, ctx.lifespan_context)["melodi_index_service"]


def get_melodi_api_service(ctx: Context = CurrentContext()) -> MelodiApiService:
    """Return the Melodi REST API service built at startup."""
    return cast(MelodiContext, ctx.lifespan_context)["melodi_api_service"]
