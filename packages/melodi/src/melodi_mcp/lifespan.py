"""What the MELODI tools need at runtime: their services, and the clients those need."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, TypedDict, cast

from diffusion_core import HealthCheck
from diffusion_core.elasticsearch import elasticsearch_lifespan
from elasticsearch import ApiError, AsyncElasticsearch
from elasticsearch import TransportError as ElasticsearchTransportError
from fastmcp import FastMCP
from fastmcp.server.lifespan import Lifespan, lifespan
from httpx import AsyncClient, Timeout
from httpx import TransportError as HttpTransportError

from .services.api_service import MelodiApiService
from .services.index_service import MelodiIndexService
from .settings import Settings

logger = logging.getLogger(__name__)

# Honest identity -- these APIs need no browser spoofing. Hardcoded: bump with pyproject.toml maybe.
USER_AGENT = "McpDiffusion/0.1.0"


class MelodiContext(TypedDict):
    """The lifespan-context keys the Melodi family contributes."""

    elasticsearch_client: AsyncElasticsearch
    melodi_http_client: AsyncClient
    melodi_index_service: MelodiIndexService
    melodi_api_service: MelodiApiService


@asynccontextmanager
async def open_melodi_services(
    elasticsearch_client: AsyncElasticsearch,
    data_base_url: str,
    request_timeout_seconds: int,
    connect_timeout_seconds: int,
    datasets_index: str,
    columns_index: str,
) -> AsyncIterator[MelodiContext]:
    """Build the MELODI services and close the API client on shutdown.

    Takes the Elasticsearch client instead of opening one; the brick's own lifespan provides it.
    """
    http_client = AsyncClient(
        base_url=data_base_url,
        headers={"User-Agent": USER_AGENT},
        timeout=Timeout(
            request_timeout_seconds,
            connect=connect_timeout_seconds,
        ),
    )
    logger.info("MELODI client initialized for %s", data_base_url)
    try:
        yield {
            "elasticsearch_client": elasticsearch_client,
            "melodi_http_client": http_client,
            "melodi_index_service": MelodiIndexService(
                elasticsearch_client=elasticsearch_client,
                datasets_index=datasets_index,
                columns_index=columns_index,
            ),
            "melodi_api_service": MelodiApiService(http_client=http_client),
        }
    finally:
        await http_client.aclose()


def build_health_check(settings: Settings) -> HealthCheck:
    """Build bounded reachability checks for the backends this lifespan opens."""

    async def check(context: Any | None) -> dict[str, bool]:
        if context is None:
            return {
                "elasticsearch": False,
                "melodi_api": False,
            }

        melodi_context = cast(MelodiContext, context)

        async def check_elasticsearch() -> bool:
            try:
                async with asyncio.timeout(settings.health_probe_timeout_seconds):
                    return bool(await melodi_context["elasticsearch_client"].ping())
            except (ApiError, ElasticsearchTransportError, TimeoutError):
                return False

        async def check_melodi_api() -> bool:
            try:
                async with asyncio.timeout(settings.health_probe_timeout_seconds):
                    response = await melodi_context["melodi_http_client"].get(
                        "",
                        timeout=settings.health_probe_timeout_seconds,
                    )
                return response.status_code < 500
            except (HttpTransportError, TimeoutError):
                return False

        elasticsearch_ready, melodi_api_ready = await asyncio.gather(
            check_elasticsearch(),
            check_melodi_api(),
        )
        return {
            "elasticsearch": elasticsearch_ready,
            "melodi_api": melodi_api_ready,
        }

    return check


def build_lifespan(settings: Settings) -> Lifespan:
    """Return the lifespan this brick runs on its own: its Elasticsearch client, then its services.

    The brick owns the connection (split decision C3), so the cluster going down takes out this
    brick rather than the whole family.
    """

    @lifespan
    async def melodi_lifespan(_server: FastMCP[Any]) -> AsyncIterator[MelodiContext]:
        # The startup validator guarantees a host, which is what lets the client take a plain `str`.
        async with AsyncExitStack() as stack:
            elasticsearch_client = await stack.enter_async_context(
                elasticsearch_lifespan(
                    host=cast(str, settings.es_host),
                    tls_verify=settings.es_tls_verify,
                    request_timeout_seconds=settings.es_request_timeout_seconds,
                    max_retries=settings.es_max_retries,
                )
            )
            yield await stack.enter_async_context(
                open_melodi_services(
                    elasticsearch_client=elasticsearch_client,
                    data_base_url=settings.melodi_data_base_url,
                    request_timeout_seconds=settings.melodi_request_timeout_seconds,
                    connect_timeout_seconds=settings.melodi_connect_timeout_seconds,
                    datasets_index=settings.es_index_melodi_datasets,
                    columns_index=settings.es_index_melodi_columns,
                )
            )

    return melodi_lifespan
