"""Stub services: shaped like the real ones, with no network behind them.

The tools receive their services through `Depends`, which reads the lifespan context, so a
server built on these stubs exercises registration, schema generation, dependency injection
and the error contract end to end while every call stays in process.

Every fake records the arguments of the calls it received, so a test can assert on what a
tool actually forwarded, not only on what it returned.
"""

from typing import Any

from insee_mcp.models import DocumentHit, DocumentResult
from melodi_mcp.models import ColumnResult, DatasetSearchResult
from rmes_mcp.models import GraphRow, ResourceProperty
from rmes_mcp.services.graph_store_service import SparqlResponse


class StubService:
    """Recording base: every stub call appends its arguments, or raises the wired error."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _answer(self, arguments: dict[str, Any], value: Any) -> Any:
        self.calls.append(arguments)
        error = getattr(self, "error", None)
        if error is not None:
            raise error
        return value

    def arguments_of(self, index: int = 0) -> dict[str, Any]:
        """The recorded arguments of one call, oldest first."""
        return self.calls[index]


class FakeInseeIndexService(StubService):
    """Stands in for InseeIndexService and its three searches."""

    def __init__(
        self,
        hits: list[DocumentHit] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.hits = hits if hits is not None else []
        self.error = error

    async def search_documents(
        self,
        **arguments: Any,
    ) -> list[DocumentHit]:
        return self._answer(arguments, self.hits)

    async def search_conjoncture(
        self,
        **arguments: Any,
    ) -> list[DocumentHit]:
        return self._answer(arguments, self.hits)

    async def search_chiffrecle(
        self,
        **arguments: Any,
    ) -> list[DocumentHit]:
        return self._answer(arguments, self.hits)


class FakeInseeDocumentService(StubService):
    """Stands in for InseeDocumentService.fetch_documents."""

    def __init__(
        self,
        results: list[DocumentResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.results = results if results is not None else []
        self.error = error

    async def fetch_documents(
        self,
        **arguments: Any,
    ) -> list[DocumentResult]:
        return self._answer(arguments, self.results)


class FakeMelodiIndexService(StubService):
    """Stands in for MelodiIndexService's catalogue and modality searches."""

    def __init__(
        self,
        datasets: list[DatasetSearchResult] | None = None,
        columns: list[ColumnResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.datasets = datasets if datasets is not None else []
        self.columns = columns if columns is not None else []
        self.error = error

    async def search_datasets(
        self,
        **arguments: Any,
    ) -> list[DatasetSearchResult]:
        return self._answer(arguments, self.datasets)

    async def search_columns(
        self,
        **arguments: Any,
    ) -> list[ColumnResult]:
        return self._answer(arguments, self.columns)


class FakeMelodiApiService(StubService):
    """Stands in for MelodiApiService.fetch_observations; rows are the upstream's raw dicts."""

    def __init__(
        self,
        observations: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.observations = observations if observations is not None else []
        self.error = error

    async def fetch_observations(
        self,
        **arguments: Any,
    ) -> list[dict[str, Any]]:
        return self._answer(arguments, self.observations)


class FakeRmesGraphStoreService(StubService):
    """Stands in for RmesGraphStoreService: SPARQL execution, graph listing, resource describe."""

    def __init__(
        self,
        response: SparqlResponse | None = None,
        graph_rows: list[GraphRow] | None = None,
        properties: list[ResourceProperty] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.response = response if response is not None else SparqlResponse()
        self.graph_rows = graph_rows if graph_rows is not None else []
        self.properties = properties if properties is not None else []
        self.error = error
        # The tools read this off the service and pass it to the pure taxonomy functions.
        self.graph_base_uri = "http://rdf.insee.fr/graphes/"

    async def execute(
        self,
        **arguments: Any,
    ) -> SparqlResponse:
        return self._answer(arguments, self.response)

    async def fetch_graph_rows(self) -> list[GraphRow]:
        return self._answer({}, self.graph_rows)

    async def describe_resource(
        self,
        **arguments: Any,
    ) -> list[ResourceProperty]:
        return self._answer(arguments, self.properties)
