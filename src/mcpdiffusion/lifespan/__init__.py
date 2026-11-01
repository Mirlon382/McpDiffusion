"""Startup and shutdown: build only what the enabled tool families need.

Each source contributes its own context fragment and closes its own clients. The exit stack
unwinds them in reverse, so a family that was never built is never torn down.

This is the composition root: it is the one place that reads the whole `Settings`, so nothing
below it has to.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from typing import Any, cast

from fastmcp import FastMCP
from fastmcp.server.lifespan import Lifespan, lifespan

from ..settings import Settings
from .elasticsearch import elasticsearch_lifespan
from .insee import InseeContext, insee_lifespan
from .melodi import MelodiContext, melodi_lifespan
from .rmes import RmesContext, rmes_lifespan


class AppContext(InseeContext, MelodiContext, RmesContext, total=False):
    """Every lifespan-context key the server can yield, keyed by the family that contributes it.

    Only the enabled families' keys are present at runtime; the `Depends` accessors in
    `dependencies/` cast to the per-source fragment they read. A missing key means a tool family
    was called that this process never built -- a KeyError, not something a schema can reach.
    """


def build_lifespan(settings: Settings) -> Lifespan:
    """Return the lifespan FastMCP runs, wired for the families that are enabled."""

    @lifespan
    async def app_lifespan(_server: FastMCP[Any]) -> AsyncIterator[AppContext]:
        # insee.fr and Melodi search the same index, so they share one client. The settings
        # validator guarantees a host whenever either is enabled, which is what makes `es_host`
        # non-None here and lets the client take a plain `str`.
        es_host = settings.es_host if (settings.enable_insee_tools or settings.enable_melodi_tools) else None

        async with AsyncExitStack() as stack:
            # A loose accumulator because the merges are flag-driven; the contract is fixed at
            # the yield below, which is the only edge FastMCP and the `Depends` accessors read.
            context: dict[str, Any] = {}

            if es_host is not None:
                elasticsearch_client = await stack.enter_async_context(
                    elasticsearch_lifespan(
                        host=es_host,
                        tls_verify=settings.es_tls_verify,
                        request_timeout_seconds=settings.es_request_timeout_seconds,
                        max_retries=settings.es_max_retries,
                    )
                )

                if settings.enable_insee_tools:
                    context |= await stack.enter_async_context(
                        insee_lifespan(
                            elasticsearch_client=elasticsearch_client,
                            base_url=settings.insee_base_url,
                            request_timeout_seconds=settings.insee_request_timeout_seconds,
                            connect_timeout_seconds=settings.insee_connect_timeout_seconds,
                            publications_index=settings.es_index_publications,
                            document_max_markdown_chars=settings.insee_document_max_markdown_chars,
                        )
                    )

                if settings.enable_melodi_tools:
                    context |= await stack.enter_async_context(
                        melodi_lifespan(
                            elasticsearch_client=elasticsearch_client,
                            data_base_url=settings.melodi_data_base_url,
                            request_timeout_seconds=settings.melodi_request_timeout_seconds,
                            connect_timeout_seconds=settings.melodi_connect_timeout_seconds,
                            datasets_index=settings.es_index_melodi_datasets,
                            columns_index=settings.es_index_melodi_columns,
                        )
                    )

            if settings.enable_rmes_tools:
                context |= await stack.enter_async_context(
                    rmes_lifespan(
                        sparql_endpoint_url=settings.rmes_sparql_endpoint_url,
                        graph_base_uri=settings.rmes_graph_base_uri,
                        graph_listing_timeout_seconds=settings.rmes_graph_listing_timeout_seconds,
                        graph_listing_max_rows=settings.rmes_graph_listing_max_rows,
                        graph_cache_ttl_seconds=settings.rmes_graph_cache_ttl_seconds,
                    )
                )

            yield cast(AppContext, context)

    return app_lifespan
