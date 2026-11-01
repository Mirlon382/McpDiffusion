"""The MCP boundary: registration, published schemas, injection, and the error contract.

These tests drive the real tool layer through an in-memory `Client` and stub services, so a tool
rename, a dependency leaking into the schema, a lost description, or an error-message regression
fails here rather than in front of a connected client. The 12 published names are a live contract
(see `docs/review-mcp-layer.md`); this module is what enforces it in the suite.
"""

import inspect
from typing import Any

from diffusion_core.errors import AppToolError, ErrorCode
from fastmcp import FastMCP

from mcpdiffusion.models.rmes import GraphRow
from mcpdiffusion.tools import register_tools
from mcpdiffusion.tools.insee.get_document_tool import get_insee_document
from mcpdiffusion.tools.insee.get_homepage_tool import get_insee_homepage
from mcpdiffusion.tools.insee.search_chiffrecle_tool import search_insee_chiffrecle
from mcpdiffusion.tools.insee.search_conjoncture_tool import search_insee_conjoncture
from mcpdiffusion.tools.insee.search_documents_tool import search_insee_documents
from mcpdiffusion.tools.melodi.get_observations_tool import get_melodi_observations
from mcpdiffusion.tools.melodi.search_datasets_tool import search_melodi_datasets
from mcpdiffusion.tools.melodi.search_modalities_tool import search_melodi_modalities
from mcpdiffusion.tools.rmes.describe_resource_tool import describe_rmes_resource
from mcpdiffusion.tools.rmes.run_sparql_tool import run_rmes_sparql
from mcpdiffusion.tools.rmes.search_graphs_tool import search_rmes_graphs
from mcpdiffusion.tools.send_feedback_tool import send_feedback
from tests.conftest import (
    ALL_TOOL_NAMES,
    INJECTED_PARAMETERS,
    build_test_mcp,
    call_tool,
    make_settings,
    result_text,
    tool_map,
)
from tests.fakes import FakeMelodiIndexService, FakeRmesGraphStoreService

# Every published name, bound to the function whose docstring must produce its description.
TOOL_FUNCTIONS: dict[str, Any] = {
    "search_insee_documents": search_insee_documents,
    "get_insee_homepage": get_insee_homepage,
    "get_insee_document": get_insee_document,
    "search_insee_conjoncture": search_insee_conjoncture,
    "search_insee_chiffrecle": search_insee_chiffrecle,
    "search_melodi_datasets": search_melodi_datasets,
    "search_melodi_modalities": search_melodi_modalities,
    "get_melodi_observations": get_melodi_observations,
    "search_rmes_graphs": search_rmes_graphs,
    "describe_rmes_resource": describe_rmes_resource,
    "run_rmes_sparql": run_rmes_sparql,
    "send_feedback": send_feedback,
}


class TestRegistration:
    """The published inventory is the live contract: renaming or dropping a tool breaks consumers."""

    async def test_the_server_publishes_exactly_the_expected_tools(self, mcp: FastMCP) -> None:
        published = set(await tool_map(mcp))
        assert published == set(ALL_TOOL_NAMES)
        assert len(ALL_TOOL_NAMES) == len(TOOL_FUNCTIONS) == 12


class TestPublishedSchemas:
    """What the LLM is shown: descriptions on everything it must use, injections hidden from it."""

    async def test_dependency_parameters_never_appear_in_a_schema(self, mcp: FastMCP) -> None:
        for tool in (await tool_map(mcp)).values():
            properties = tool.input_schema["properties"]
            assert not INJECTED_PARAMETERS & set(properties), tool.name

    async def test_every_description_comes_from_the_function_docstring(self, mcp: FastMCP) -> None:
        published = await tool_map(mcp)
        for name, function in TOOL_FUNCTIONS.items():
            first_line = inspect.cleandoc(function.__doc__ or "").splitlines()[0]
            assert first_line in published[name].description, name

    async def test_every_published_parameter_carries_a_description(self, mcp: FastMCP) -> None:
        for tool in (await tool_map(mcp)).values():
            for parameter, schema in tool.input_schema["properties"].items():
                assert schema.get("description"), f"{tool.name}.{parameter}"


class TestDependencyInjection:
    """A call traverses schema validation, `Depends` resolution and the lifespan context."""

    async def test_a_tool_call_reaches_the_service_from_the_lifespan_context(
        self,
        mcp: FastMCP,
        graph_store_service: FakeRmesGraphStoreService,
    ) -> None:
        graph_store_service.graph_rows.append(
            GraphRow(
                graph="http://rdf.insee.fr/graphes/concepts/structures/famille",
                triples=4200,
            ),
        )

        result = await call_tool(mcp, "search_rmes_graphs")

        assert not result.is_error
        assert len(graph_store_service.calls) == 1
        assert result.structured_content["total_graphs_matched"] == 1

    async def test_llm_arguments_are_validated_and_forwarded_verbatim(
        self,
        mcp: FastMCP,
        melodi_index_service: FakeMelodiIndexService,
    ) -> None:
        result = await call_tool(
            mcp,
            "search_melodi_datasets",
            {
                "query": "indice des prix a la consommation",
                "number_of_datasets": 3,
            },
        )

        assert not result.is_error
        forwarded = melodi_index_service.arguments_of(0)
        assert forwarded["query"] == "indice des prix a la consommation"
        assert forwarded["number_of_datasets"] == 3

    async def test_the_feedback_tool_needs_no_service(self, mcp: FastMCP) -> None:
        result = await call_tool(
            mcp,
            "send_feedback",
            {
                "author": "suite",
                "feedback": "Schema check from the MCP-layer tests.",
            },
        )

        assert not result.is_error
        assert result.structured_content["message"] == "Feedback recorded successfully."


class TestErrorContract:
    """The two error paths across the MCP boundary: ours reaches the caller, bugs are masked."""

    async def test_an_app_tool_error_reaches_the_client_with_code_and_message(
        self,
        lifespan_context: dict[str, Any],
    ) -> None:
        failing = FakeRmesGraphStoreService(
            error=AppToolError(
                ErrorCode.NOT_FOUND,
                "Graph listing is empty in this build.",
            ),
        )
        mcp = build_test_mcp(
            {
                **lifespan_context,
                "rmes_graph_store_service": failing,
            },
        )

        result = await call_tool(mcp, "search_rmes_graphs")

        assert result.is_error
        assert "[NOT_FOUND] Graph listing is empty in this build." in result_text(result)

    async def test_an_unexpected_exception_is_masked_from_the_client(
        self,
        lifespan_context: dict[str, Any],
    ) -> None:
        failing = FakeRmesGraphStoreService(
            error=RuntimeError("connection string es-secret:9200 leaked here"),
        )
        mcp = build_test_mcp(
            {
                **lifespan_context,
                "rmes_graph_store_service": failing,
            },
        )

        result = await call_tool(mcp, "search_rmes_graphs")

        assert result.is_error
        assert "es-secret" not in result_text(result)


class TestFlagGating:
    """A disabled family is unregistered, not hidden: its tools are absent from `tools/list`."""

    async def test_only_enabled_families_are_published(self) -> None:
        mcp = FastMCP("gated")
        register_tools(
            mcp=mcp,
            settings=make_settings(
                enable_insee_tools=False,
                enable_melodi_tools=False,
                enable_rmes_tools=False,
            ),
        )

        published = set(await tool_map(mcp))

        assert published == {"send_feedback"}
