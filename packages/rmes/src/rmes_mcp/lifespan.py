"""What the RMES tools need at runtime: one HTTP client, and the service built on it."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, TypedDict, cast

from diffusion_core import HealthCheck
from fastmcp import FastMCP
from fastmcp.server.lifespan import Lifespan, lifespan
from httpx import AsyncClient
from httpx import TransportError as HttpTransportError

from .services.graph_store_service import RmesGraphStoreService
from .settings import Settings

logger = logging.getLogger(__name__)

# Honest identity -- these APIs need no browser spoofing. Hardcoded: bump with pyproject.toml maybe.
USER_AGENT = "McpDiffusion/0.1.0"


class RmesContext(TypedDict):
    """The lifespan-context keys the RMES family contributes."""

    rmes_http_client: AsyncClient
    sparql_endpoint_url: str
    rmes_graph_store_service: RmesGraphStoreService


@asynccontextmanager
async def open_rmes_services(
    sparql_endpoint_url: str,
    graph_base_uri: str,
    graph_listing_timeout_seconds: float,
    graph_listing_max_rows: int,
    graph_cache_ttl_seconds: float,
) -> AsyncIterator[RmesContext]:
    """Build the RMES service and close its client on shutdown.

    RMES passes its own timeout per query, so this client sets none.
    """
    http_client = AsyncClient(headers={"User-Agent": USER_AGENT})
    logger.info("SPARQL client initialized")
    try:
        yield {
            "rmes_http_client": http_client,
            "sparql_endpoint_url": sparql_endpoint_url,
            "rmes_graph_store_service": RmesGraphStoreService(
                http_client=http_client,
                sparql_endpoint_url=sparql_endpoint_url,
                graph_base_uri=graph_base_uri,
                graph_listing_timeout_seconds=graph_listing_timeout_seconds,
                graph_listing_max_rows=graph_listing_max_rows,
                graph_cache_ttl_seconds=graph_cache_ttl_seconds,
            ),
        }
    finally:
        await http_client.aclose()


def build_health_check(settings: Settings) -> HealthCheck:
    """Build a bounded, read-only ASK probe against the SPARQL endpoint."""

    async def check(context: Any | None) -> dict[str, bool]:
        if context is None:
            return {"sparql": False}

        rmes_context = cast(RmesContext, context)
        try:
            async with asyncio.timeout(settings.health_probe_timeout_seconds):
                response = await rmes_context["rmes_http_client"].post(
                    rmes_context["sparql_endpoint_url"],
                    data={"query": "ASK {}"},
                    headers={"Accept": "application/sparql-results+json"},
                    timeout=settings.health_probe_timeout_seconds,
                )
            sparql_ready = response.is_success
        except (HttpTransportError, TimeoutError):
            sparql_ready = False

        return {"sparql": sparql_ready}

    return check


def build_lifespan(settings: Settings) -> Lifespan:
    """Return the lifespan this brick runs on its own.

    Nothing to connect to beyond a public endpoint, which is the point of this brick: it starts
    with no infrastructure behind it.
    """

    @lifespan
    async def rmes_lifespan(_server: FastMCP[Any]) -> AsyncIterator[RmesContext]:
        async with open_rmes_services(
            sparql_endpoint_url=settings.rmes_sparql_endpoint_url,
            graph_base_uri=settings.rmes_graph_base_uri,
            graph_listing_timeout_seconds=settings.rmes_graph_listing_timeout_seconds,
            graph_listing_max_rows=settings.rmes_graph_listing_max_rows,
            graph_cache_ttl_seconds=settings.rmes_graph_cache_ttl_seconds,
        ) as services:
            yield services

    return rmes_lifespan
