"""Shared test fixtures: brick tool functions run in memory against stub services.

These tests do not talk to Elasticsearch, insee.fr or RMES. The server boot tests separately
exercise the mounted aggregate and its child lifespans.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.lifespan import lifespan
from insee_mcp.settings import Settings as InseeSettings
from insee_mcp.tools import register_tools as register_insee_tools
from melodi_mcp.settings import Settings as MelodiSettings
from melodi_mcp.tools import register_tools as register_melodi_tools
from rmes_mcp.settings import Settings as RmesSettings
from rmes_mcp.tools import register_tools as register_rmes_tools

from tests.fakes import (
    FakeInseeDocumentService,
    FakeInseeIndexService,
    FakeMelodiApiService,
    FakeMelodiIndexService,
    FakeRmesGraphStoreService,
)

# A host that cannot resolve: the validator demands one, and these tests never dial it.
FAKE_ES_HOST = "http://elasticsearch.invalid:9200"

# The tools each brick publishes, in the order it registers them (decision 4: no renames).
BRICK_TOOL_NAMES = {
    "insee": [
        "search_insee_documents",
        "get_insee_homepage",
        "get_insee_document",
        "search_insee_conjoncture",
        "search_insee_chiffrecle",
    ],
    "melodi": [
        "search_melodi_datasets",
        "search_melodi_modalities",
        "get_melodi_observations",
    ],
    "rmes": [
        "search_rmes_graphs",
        "describe_rmes_resource",
        "run_rmes_sparql",
    ],
}

ALL_TOOL_NAMES = [
    *BRICK_TOOL_NAMES["insee"],
    *BRICK_TOOL_NAMES["melodi"],
    *BRICK_TOOL_NAMES["rmes"],
]

# Parameter names that `Depends` must keep out of every published schema.
INJECTED_PARAMETERS = {
    "insee_index_service",
    "insee_document_service",
    "melodi_index_service",
    "melodi_api_service",
    "rmes_graph_store_service",
}


def build_test_mcp(lifespan_context: dict[str, Any]) -> FastMCP:
    """A FastMCP server whose lifespan yields the stub services the `Depends` accessors read."""

    @lifespan
    async def stub_lifespan(_server: FastMCP[Any]) -> AsyncIterator[dict[str, Any]]:
        yield lifespan_context

    mcp = FastMCP(
        "test-server",
        mask_error_details=True,
        lifespan=stub_lifespan,
    )
    register_insee_tools(
        mcp,
        InseeSettings(_env_file=None, es_host=FAKE_ES_HOST),
    )
    register_melodi_tools(
        mcp,
        MelodiSettings(_env_file=None, es_host=FAKE_ES_HOST),
    )
    register_rmes_tools(
        mcp,
        RmesSettings(_env_file=None),
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
