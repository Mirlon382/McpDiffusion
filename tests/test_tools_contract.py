"""The published tool contract: registration, schemas, injection, forwarding, and errors.

Every test drives the real functions from `mcpdiffusion.tools` through an in-memory `Client`,
against the stub services from `tests.fakes`. What is under test is the MCP layer itself: what
the model sees in the schema, what it gets back, and what never leaks.
"""

from typing import Any

import pytest
from diffusion_core.errors import AppToolError, ErrorCode

from mcpdiffusion.data.insee.indicators import KEY_INDICATORS
from mcpdiffusion.models.insee import DocumentHit, DocumentResult
from mcpdiffusion.models.melodi import (
    ColumnResult,
    DatasetDescription,
    DatasetSearchResult,
    Modality,
)
from mcpdiffusion.models.rmes import (
    MAX_QUERY_TIMEOUT_SECONDS,
    GraphRow,
    ResourceProperty,
)
from mcpdiffusion.services.rmes.graph_store_service import SparqlResponse
from tests.conftest import (
    ALL_TOOL_NAMES,
    INJECTED_PARAMETERS,
    build_test_mcp,
    call_tool,
    make_settings,
    result_text,
    tool_map,
)
from tests.fakes import FakeInseeIndexService


class TestPublishedSurface:
    """What a client sees at connect: every name, a description, and no injected plumbing."""

    async def test_all_twelve_tools_are_registered(self, mcp: Any) -> None:
        tools = await tool_map(mcp)
        assert list(tools) == ALL_TOOL_NAMES

    async def test_injected_services_stay_out_of_every_schema(self, mcp: Any) -> None:
        for tool in (await tool_map(mcp)).values():
            visible = set(tool.input_schema["properties"])
            assert visible.isdisjoint(INJECTED_PARAMETERS | {"ctx"}), tool.name

    async def test_every_tool_publishes_a_description(self, mcp: Any) -> None:
        for tool in (await tool_map(mcp)).values():
            assert tool.description and len(tool.description) > 40, tool.name

    async def test_field_descriptions_reach_the_parameter_schema(self, mcp: Any) -> None:
        documents = (await tool_map(mcp))["search_insee_documents"]
        assert "Natural-language search query" in documents.input_schema["properties"]["query"]["description"]

    async def test_disabled_families_are_absent_not_hidden(self, lifespan_context: dict[str, Any]) -> None:
        settings = make_settings(
            enable_insee_tools=False,
            enable_melodi_tools=False,
            enable_rmes_tools=False,
        )
        tools = await tool_map(build_test_mcp(lifespan_context, settings))
        assert list(tools) == ["send_feedback"]


class TestInseeSearchTools:
    async def test_search_documents_forwards_arguments_and_counts_hits(
        self,
        mcp: Any,
        index_service: FakeInseeIndexService,
    ) -> None:
        index_service.hits = [
            DocumentHit(
                id="1",
                score=2.5,
                url="/fr/statistiques/1",
                titre="Chomage",
            ),
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="search_insee_documents",
            arguments={
                "query": "chomage 2024",
                "number_of_results": 3,
            },
        )
        assert not result.is_error
        assert result.structured_content["count"] == 1
        forwarded = index_service.arguments_of()
        assert forwarded["query"] == "chomage 2024"
        assert forwarded["number_of_results"] == 3
        assert forwarded["theme"] == "ALL"  # the documented default, forwarded as a value
        assert forwarded["geo_level"] == "FRANCE"
        assert forwarded["year_of_reference"] is None

    async def test_conjoncture_and_chiffrecle_share_the_result_envelope(
        self,
        mcp: Any,
        index_service: FakeInseeIndexService,
    ) -> None:
        index_service.hits = [
            DocumentHit(
                id="2",
                score=1.0,
                url="/fr/statistiques/2",
            ),
        ]
        for tool_name in ("search_insee_conjoncture", "search_insee_chiffrecle"):
            result = await call_tool(
                mcp=mcp,
                tool_name=tool_name,
                arguments={"query": "inflation"},
            )
            assert not result.is_error, tool_name
            assert set(result.structured_content) == {"results", "count"}
            assert result.structured_content["count"] == 1
            assert result.structured_content["results"][0]["id"] == "2"

    async def test_a_typed_failure_reaches_the_caller_verbatim(
        self,
        mcp: Any,
        index_service: FakeInseeIndexService,
    ) -> None:
        index_service.error = AppToolError(
            ErrorCode.BACKEND_UNAVAILABLE,
            "insee.fr search backend unreachable (TransportError). Verify ES_HOST and try again.",
            retryable=True,
        )
        result = await call_tool(
            mcp=mcp,
            tool_name="search_insee_documents",
            arguments={"query": "x"},
        )
        assert result.is_error
        assert "[BACKEND_UNAVAILABLE, retryable]" in result_text(result)

    async def test_an_unexpected_bug_is_masked_but_still_fails_the_call(
        self,
        mcp: Any,
        index_service: FakeInseeIndexService,
    ) -> None:
        # mask_error_details=True: internal text must not leave the process.
        index_service.error = RuntimeError("password=hunter2 on es-secret:9200")
        result = await call_tool(
            mcp=mcp,
            tool_name="search_insee_documents",
            arguments={"query": "x"},
        )
        assert result.is_error
        assert "hunter2" not in result_text(result)
        assert "es-secret" not in result_text(result)

    @pytest.mark.parametrize("number_of_results", [0, 999])
    async def test_schema_bounds_reject_before_any_service_call(
        self,
        mcp: Any,
        index_service: FakeInseeIndexService,
        number_of_results: int,
    ) -> None:
        result = await call_tool(
            mcp=mcp,
            tool_name="search_insee_documents",
            arguments={
                "query": "x",
                "number_of_results": number_of_results,
            },
        )
        assert result.is_error
        assert index_service.calls == []


class TestGetInseeDocument:
    async def test_urls_and_flags_reach_the_document_service(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        document_service = lifespan_context["insee_document_service"]
        document_service.results = [
            DocumentResult(
                id="/fr/statistiques/42",
                status="success",
                markdown_content="#titre",
            ),
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="get_insee_document",
            arguments={"document_urls": ["/fr/statistiques/42"]},
        )
        assert not result.is_error
        assert result.structured_content["count"] == 1
        forwarded = document_service.arguments_of()
        assert forwarded["document_urls"] == ["/fr/statistiques/42"]
        assert forwarded["include_table_of_contents"] is True
        assert forwarded["truncate_content"] is True

    async def test_more_urls_than_the_schema_allows_are_rejected(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        document_service = lifespan_context["insee_document_service"]
        result = await call_tool(
            mcp=mcp,
            tool_name="get_insee_document",
            arguments={"document_urls": [f"/fr/statistiques/{n}" for n in range(11)]},
        )
        assert result.is_error
        assert document_service.calls == []


class TestHomepage:
    async def test_homepage_returns_the_indicator_table(self, mcp: Any) -> None:
        result = await call_tool(
            mcp=mcp,
            tool_name="get_insee_homepage",
        )
        assert not result.is_error
        assert result.structured_content["count"] == len(KEY_INDICATORS)
        assert result.structured_content["indicators"][0]["key"] == KEY_INDICATORS[0]["cle"]


class TestMelodiTools:
    async def test_search_datasets_forwards_the_year_window_defaults(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        melodi_index = lifespan_context["melodi_index_service"]
        melodi_index.datasets = [
            DatasetSearchResult(
                dataset_id="DS_PRIX",
                dataset_columns="GEO Geographie",
                dataset_description=DatasetDescription(
                    content="prix",
                    lang="fr",
                ),
                dataset_score=4.0,
            ),
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="search_melodi_datasets",
            arguments={"query": "indice des prix"},
        )
        assert not result.is_error
        assert result.structured_content["results"][0]["dataset_id"] == "DS_PRIX"
        forwarded = melodi_index.arguments_of()
        assert forwarded["start_year"] == 1900
        assert forwarded["end_year"] == 2100
        assert forwarded["number_of_datasets"] == 5

    async def test_search_modalities_returns_columns(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        melodi_index = lifespan_context["melodi_index_service"]
        melodi_index.columns = [
            ColumnResult(
                column_code="GEO",
                column_metadata="geographie",
                matching_modalities=[
                    Modality(
                        code="FR",
                        label_en="France",
                        label_fr="France",
                        score=1.5,
                    ),
                ],
            ),
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="search_melodi_modalities",
            arguments={
                "dataset_id": "DS_PRIX",
                "column_ids": ["GEO"],
                "query": "france",
            },
        )
        assert not result.is_error
        first = result.structured_content["results"][0]
        assert first["column_code"] == "GEO"
        assert first["matching_modalities"][0]["code"] == "FR"

    async def test_observations_filter_by_year_then_truncate(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        melodi_api = lifespan_context["melodi_api_service"]
        melodi_api.observations = [
            {"dimensions": {"TIME_PERIOD": "2024-01"}, "measure": 1},
            {"dimensions": {"TIME_PERIOD": "2024-08"}, "measure": 2},
            {"dimensions": {"TIME_PERIOD": "2023-01"}, "measure": 3},
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="get_melodi_observations",
            arguments={
                "dataset_id": "DS_PRIX",
                "years": [2024],
                "column_filters": {},
                "number_of_observations": 1,
            },
        )
        assert not result.is_error
        assert result.structured_content["count"] == 1
        assert result.structured_content["observations"] == [{"dimensions": {"TIME_PERIOD": "2024-01"}, "measure": 1}]

    async def test_malformed_rows_survive_a_full_fetch(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        # The regression: one null-dimensions row used to take the whole batch down.
        melodi_api = lifespan_context["melodi_api_service"]
        melodi_api.observations = [
            {"dimensions": {"TIME_PERIOD": "2024-01"}, "measure": 1},
            {"dimensions": None},
            {},
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="get_melodi_observations",
            arguments={
                "dataset_id": "DS_PRIX",
                "years": [],
                "column_filters": {},
            },
        )
        assert not result.is_error
        assert result.structured_content["count"] == 3


class TestRmesTools:
    async def test_a_json_answer_comes_back_in_the_json_shape(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        graph_store.response = SparqlResponse(
            variables=["?s"],
            bindings=[{"?s": {"type": "uri", "value": "http://example.org/x"}}],
            limit_added=200,
            hint="LIMIT was added",
        )
        result = await call_tool(
            mcp=mcp,
            tool_name="run_rmes_sparql",
            arguments={"sparql_query": "SELECT ?s WHERE { ?s ?p ?o }"},
        )
        assert not result.is_error
        assert result.structured_content["format"] == "json"
        assert result.structured_content["limit_added"] == 200
        forwarded = graph_store.arguments_of()
        assert forwarded["timeout_seconds"] == 20.0
        assert forwarded["max_rows"] == 200

    async def test_the_timeout_is_clamped_to_the_schema_bound(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        result = await call_tool(
            mcp=mcp,
            tool_name="run_rmes_sparql",
            arguments={
                "sparql_query": "SELECT ?s WHERE { ?s ?p ?o }",
                "timeout_seconds": 600.0,
            },
        )
        assert not result.is_error
        assert graph_store.arguments_of()["timeout_seconds"] == MAX_QUERY_TIMEOUT_SECONDS

    async def test_a_construct_answer_comes_back_as_turtle(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        graph_store.response = SparqlResponse(turtle="@prefix : <http://x> .\n")
        result = await call_tool(
            mcp=mcp,
            tool_name="run_rmes_sparql",
            arguments={"sparql_query": "CONSTRUCT WHERE { ?s ?p ?o }"},
        )
        assert not result.is_error
        assert result.structured_content["format"] == "turtle"
        assert result.structured_content["turtle"].startswith("@prefix")

    async def test_a_blank_query_is_rejected_with_the_contract_marker(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        result = await call_tool(
            mcp=mcp,
            tool_name="run_rmes_sparql",
            arguments={"sparql_query": "   "},
        )
        assert result.is_error
        assert "[INVALID_INPUT]" in result_text(result)
        assert graph_store.calls == []

    async def test_graph_listing_condenses_by_default_and_narrows_on_substring(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        graph_store.graph_rows = [
            GraphRow(
                graph="http://rdf.insee.fr/graphes/codes/naf2025",
                triples=12,
            ),
            GraphRow(
                graph="http://rdf.insee.fr/graphes/produits/essentiels",
                triples=3,
            ),
        ]
        everything = await call_tool(
            mcp=mcp,
            tool_name="search_rmes_graphs",
        )
        assert not everything.is_error
        assert everything.structured_content["total_graphs_matched"] == 2

        narrowed = await call_tool(
            mcp=mcp,
            tool_name="search_rmes_graphs",
            arguments={"graph_uri_substring": "naf"},
        )
        assert not narrowed.is_error
        assert narrowed.structured_content["total_graphs_matched"] == 1
        listed = [
            row["graph"] for category in narrowed.structured_content["categories"] for row in (category["graphs"] or [])
        ]
        assert listed == ["http://rdf.insee.fr/graphes/codes/naf2025"]

    async def test_describe_forwards_both_uris(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        graph_store = lifespan_context["rmes_graph_store_service"]
        graph_store.properties = [
            ResourceProperty(
                graph="http://rdf.insee.fr/graphes/codes/naf2025",
                direction="outgoing",
                predicate="http://www.w3.org/2004/02/skos/core#prefLabel",
                value="Agriculture",
            ),
        ]
        result = await call_tool(
            mcp=mcp,
            tool_name="describe_rmes_resource",
            arguments={"resource_uri": "http://id.insee.fr/codes/naf2025/section/A"},
        )
        assert not result.is_error
        assert result.structured_content["count"] == 1
        forwarded = graph_store.arguments_of()
        assert forwarded["resource_uri"] == "http://id.insee.fr/codes/naf2025/section/A"
        assert forwarded["graph_uri"] is None

    async def test_a_crafted_uri_never_reaches_the_query(
        self,
        mcp: Any,
        lifespan_context: dict[str, Any],
    ) -> None:
        # The SPARQL-injection regression: the IRI pattern is a schema bound, enforced before the tool runs.
        graph_store = lifespan_context["rmes_graph_store_service"]
        result = await call_tool(
            mcp=mcp,
            tool_name="describe_rmes_resource",
            arguments={"resource_uri": 'http://example.fr/x"> ?s ?o } UNION { GRAPH ?g { ?s ?p <y'},
        )
        assert result.is_error
        assert graph_store.calls == []


class TestFeedbackTool:
    async def test_feedback_is_recorded_and_confirmed(self, mcp: Any) -> None:
        result = await call_tool(
            mcp=mcp,
            tool_name="send_feedback",
            arguments={
                "author": "tester",
                "feedback": "search_melodi_datasets missed DS_PRIX.",
            },
        )
        assert not result.is_error
        assert result.structured_content["status"] == "success"
        assert result.structured_content["message"] == "Feedback recorded successfully."
        assert result.structured_content["timestamp"]

    async def test_an_overlong_author_is_rejected_by_the_schema(self, mcp: Any) -> None:
        result = await call_tool(
            mcp=mcp,
            tool_name="send_feedback",
            arguments={
                "author": "a" * 101,
                "feedback": "x",
            },
        )
        assert result.is_error
