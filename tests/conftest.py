"""Shared fixtures: the real tool layer, in memory, against the stub services.

Nothing here talks to Elasticsearch, insee.fr or RMES. The lifespan context is built from
`tests.fakes`, so a `Client` session exercises the same registration and dependency-injection
path the production server runs, without any I/O.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.lifespan import lifespan

from mcpdiffusion.settings import Settings
from mcpdiffusion.tools import register_tools
from tests.fakes import (
    FakeInseeDocumentService,
    FakeInseeIndexService,
    FakeMelodiApiService,
    FakeMelodiIndexService,
    FakeRmesGraphStoreService,
)

# A host that cannot resolve: the validator demands one, and these tests never dial it.
FAKE_ES_HOST = "http://elasticsearch.invalid:9200"

# The full set the server registers with every family enabled.
ALL_TOOL_NAMES = [
    "search_insee_documents",
    "get_insee_homepage",
    "get_insee_document",
    "search_insee_conjoncture",
    "search_insee_chiffrecle",
    "search_melodi_datasets",
    "search_melodi_modalities",
    "get_melodi_observations",
    "search_rmes_graphs",
    "describe_rmes_resource",
    "run_rmes_sparql",
    "send_feedback",
]

# Parameter names that `Depends` must keep out of every published schema.
INJECTED_PARAMETERS = {
    "insee_index_service",
    "insee_document_service",
    "melodi_index_service",
    "melodi_api_service",
    "rmes_graph_store_service",
}


def make_settings(**overrides: Any) -> Settings:
    """Settings that never read a `.env`: deterministic, offline, all families enabled."""
    arguments: dict[str, Any] = {
        "_env_file": None,
        "es_host": FAKE_ES_HOST,
    }
    arguments.update(overrides)
    return Settings(**arguments)


def build_test_mcp(
    lifespan_context: dict[str, Any],
    settings: Settings | None = None,
) -> FastMCP:
    """A FastMCP server whose lifespan yields the stub services the `Depends` accessors read."""

    @lifespan
    async def stub_lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
        yield lifespan_context

    mcp = FastMCP(
        "test-server",
        mask_error_details=True,
        lifespan=stub_lifespan,
    )
    register_tools(
        mcp=mcp,
        settings=settings if settings is not None else make_settings(),
    )
    return mcp


async def call_tool(
    mcp: FastMCP,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """One in-memory tool call, returned as the raw CallToolResult, errors included."""
    async with Client(mcp) as client:
        return await client.call_tool(
            tool_name,
            arguments or {},
            raise_on_error=False,
        )


async def list_tools(mcp: FastMCP) -> list[Any]:
    """The published tool list of an in-memory server."""
    async with Client(mcp) as client:
        return list(await client.list_tools())


async def tool_map(mcp: FastMCP) -> dict[str, Any]:
    """Published tools keyed by name."""
    return {tool.name: tool for tool in await list_tools(mcp)}


def result_text(result: Any) -> str:
    """The text the caller reads on failure -- the error contract lives here."""
    return "\n".join(block.text for block in result.content if block.type == "text")


@pytest.fixture
def index_service() -> FakeInseeIndexService:
    return FakeInseeIndexService()


@pytest.fixture
def document_service() -> FakeInseeDocumentService:
    return FakeInseeDocumentService()


@pytest.fixture
def melodi_index_service() -> FakeMelodiIndexService:
    return FakeMelodiIndexService()


@pytest.fixture
def melodi_api_service() -> FakeMelodiApiService:
    return FakeMelodiApiService()


@pytest.fixture
def graph_store_service() -> FakeRmesGraphStoreService:
    return FakeRmesGraphStoreService()


@pytest.fixture
def lifespan_context(
    index_service: FakeInseeIndexService,
    document_service: FakeInseeDocumentService,
    melodi_index_service: FakeMelodiIndexService,
    melodi_api_service: FakeMelodiApiService,
    graph_store_service: FakeRmesGraphStoreService,
) -> dict[str, Any]:
    """The stub services under exactly the keys the typed `AppContext` promises."""
    return {
        "insee_index_service": index_service,
        "insee_document_service": document_service,
        "melodi_index_service": melodi_index_service,
        "melodi_api_service": melodi_api_service,
        "rmes_graph_store_service": graph_store_service,
    }


@pytest.fixture
def mcp(lifespan_context: dict[str, Any]) -> FastMCP:
    return build_test_mcp(lifespan_context)
