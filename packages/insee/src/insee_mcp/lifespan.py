"""What the insee.fr tools need at runtime: their services, and the clients those need."""

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

from .services.document_service import InseeDocumentService
from .services.index_service import InseeIndexService
from .settings import Settings

logger = logging.getLogger(__name__)

# insee.fr serves different markup to unknown agents, so the scraper has to look like a browser.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


class InseeContext(TypedDict):
    """The lifespan-context keys the insee.fr family contributes."""

    elasticsearch_client: AsyncElasticsearch
    insee_http_client: AsyncClient
    insee_index_service: InseeIndexService
    insee_document_service: InseeDocumentService


@asynccontextmanager
async def open_insee_services(
    elasticsearch_client: AsyncElasticsearch,
    base_url: str,
    request_timeout_seconds: int,
    connect_timeout_seconds: int,
    publications_index: str,
    document_max_markdown_chars: int,
) -> AsyncIterator[InseeContext]:
    """Build the insee.fr services and close the scraping client on shutdown.

    Takes the Elasticsearch client instead of opening one; the brick's own lifespan provides it.
    """
    http_client = AsyncClient(
        base_url=base_url,
        headers={"User-Agent": USER_AGENT},
        timeout=Timeout(
            request_timeout_seconds,
            connect=connect_timeout_seconds,
        ),
    )
    logger.info("insee.fr client initialized for %s", base_url)
    try:
        yield {
            "elasticsearch_client": elasticsearch_client,
            "insee_http_client": http_client,
            "insee_index_service": InseeIndexService(
                elasticsearch_client=elasticsearch_client,
                publications_index=publications_index,
            ),
            "insee_document_service": InseeDocumentService(
                http_client=http_client,
                max_markdown_chars=document_max_markdown_chars,
            ),
        }
    finally:
        await http_client.aclose()


def build_health_check(settings: Settings) -> HealthCheck:
    """Build bounded reachability checks for the backends this lifespan opens."""

    async def check(context: Any | None) -> dict[str, bool]:
        if context is None:
            return {
                "elasticsearch": False,
                "insee_site": False,
            }

        insee_context = cast(InseeContext, context)

        async def check_elasticsearch() -> bool:
            try:
                async with asyncio.timeout(settings.health_probe_timeout_seconds):
                    return bool(await insee_context["elasticsearch_client"].ping())
            except (ApiError, ElasticsearchTransportError, TimeoutError):
                return False

        async def check_insee_site() -> bool:
            try:
                async with asyncio.timeout(settings.health_probe_timeout_seconds):
                    response = await insee_context["insee_http_client"].get(
                        "/",
                        timeout=settings.health_probe_timeout_seconds,
                    )
                return response.status_code < 500
            except (HttpTransportError, TimeoutError):
                return False

        elasticsearch_ready, insee_ready = await asyncio.gather(
            check_elasticsearch(),
            check_insee_site(),
        )
        return {
            "elasticsearch": elasticsearch_ready,
            "insee_site": insee_ready,
        }

    return check


def build_lifespan(settings: Settings) -> Lifespan:
    """Return the lifespan this brick runs on its own: its Elasticsearch client, then its services.

    The brick owns the connection (split decision C3), so the cluster going down takes out this
    brick rather than the whole family.
    """

    @lifespan
    async def insee_lifespan(_server: FastMCP[Any]) -> AsyncIterator[InseeContext]:
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
                open_insee_services(
                    elasticsearch_client=elasticsearch_client,
                    base_url=settings.insee_base_url,
                    request_timeout_seconds=settings.insee_request_timeout_seconds,
                    connect_timeout_seconds=settings.insee_connect_timeout_seconds,
                    publications_index=settings.es_index_publications,
                    document_max_markdown_chars=settings.insee_document_max_markdown_chars,
                )
            )

    return insee_lifespan
