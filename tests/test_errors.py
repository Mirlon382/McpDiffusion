"""The error contract: the single type, its closed vocabulary, and the Elasticsearch translator."""

from http import HTTPStatus

import elasticsearch
import pytest
from diffusion_core.elasticsearch import elasticsearch_tool_error_handler
from diffusion_core.errors import AppToolError, ErrorCode
from elastic_transport import ApiResponseMeta, HttpHeaders, TransportError
from fastmcp.exceptions import ToolError


class TestAppToolError:
    """The message is the contract: a bracketed code, then what to do about it."""

    def test_subclasses_tool_error_so_its_message_survives_masking(self) -> None:
        assert issubclass(AppToolError, ToolError)

    def test_message_carries_the_code_as_a_marker(self) -> None:
        error = AppToolError(
            ErrorCode.NOT_FOUND,
            "Dataset DS_NOPE does not exist; get ids from search_melodi_datasets.",
        )
        assert str(error) == "[NOT_FOUND] Dataset DS_NOPE does not exist; get ids from search_melodi_datasets."

    def test_retryable_marker_is_added_only_when_set(self) -> None:
        error = AppToolError(
            ErrorCode.BACKEND_UNAVAILABLE,
            "Elasticsearch is down.",
            retryable=True,
        )
        assert str(error).startswith("[BACKEND_UNAVAILABLE, retryable]")
        assert error.retryable is True
        assert not str(
            AppToolError(
                ErrorCode.UPSTREAM_ERROR,
                "boom",
            ),
        ).endswith("retryable]")

    def test_code_and_retryable_are_attributes_not_only_text(self) -> None:
        error = AppToolError(
            ErrorCode.INVALID_INPUT,
            "query is required.",
        )
        assert error.code is ErrorCode.INVALID_INPUT
        assert error.retryable is False

    def test_vocabulary_is_a_closed_enum(self) -> None:
        assert {code.value for code in ErrorCode} == {
            "INVALID_INPUT",
            "BACKEND_UNAVAILABLE",
            "UPSTREAM_ERROR",
            "PARSE_ERROR",
            "INVALID_QUERY",
            "NOT_FOUND",
            "INTERNAL_ERROR",
        }
        assert not hasattr(ErrorCode, "UNKNOWN")


def api_error(status: int, error_reason: str) -> elasticsearch.ApiError:
    """A real ApiError: the handler branches on the class, not on duck-typed attributes."""
    meta = ApiResponseMeta(
        status=status,
        http_version="1.1",
        headers=HttpHeaders(),
        duration=0.0,
        node=None,
    )
    return elasticsearch.ApiError(
        message=f"[{status}] {error_reason}",
        meta=meta,
        body={"error": error_reason},
    )


class TestElasticsearchTranslator:
    """One boundary converts every Elasticsearch failure into the contract; the details split is deliberate:
    ApiError does not subclass TransportError, so catching one never catches the other."""

    def test_api_error_is_not_a_transport_error(self) -> None:
        assert not isinstance(api_error(404, "index_not_found_exception"), TransportError)

    async def transport_failure(self, message: str) -> AppToolError:
        with pytest.raises(AppToolError) as excinfo:
            async with elasticsearch_tool_error_handler("insee.fr"):
                raise TransportError(message)
        return excinfo.value

    async def api_failure(
        self,
        status: int,
        reason: str,
    ) -> AppToolError:
        with pytest.raises(AppToolError) as excinfo:
            async with elasticsearch_tool_error_handler("insee.fr"):
                raise api_error(status, reason)
        return excinfo.value

    async def test_transport_error_becomes_retryable_backend_unavailable(self) -> None:
        error = await self.transport_failure("Connection refused")
        assert error.code is ErrorCode.BACKEND_UNAVAILABLE
        assert error.retryable is True
        assert "insee.fr search backend unreachable" in str(error)

    async def test_the_host_never_leaves_the_process(self) -> None:
        error = await self.transport_failure("Connection to http://es-secret.internal:9200 refused")
        message = str(error)
        assert "es-secret.internal" not in message
        assert "TransportError" in message  # only the type is quoted

    async def test_missing_index_is_not_retryable_and_says_so(self) -> None:
        error = await self.api_failure(
            HTTPStatus.NOT_FOUND,
            "index_not_found_exception",
        )
        assert error.code is ErrorCode.BACKEND_UNAVAILABLE
        assert error.retryable is False
        assert "index is missing" in str(error)

    async def test_rejected_query_is_blamed_on_the_server(self) -> None:
        error = await self.api_failure(
            HTTPStatus.BAD_REQUEST,
            "parsing_exception",
        )
        assert error.code is ErrorCode.INVALID_QUERY
        assert "not in the arguments you passed" in str(error)

    async def test_auth_failures_ask_for_a_report_not_a_retry(self) -> None:
        for status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            error = await self.api_failure(status, "security_exception")
            assert error.code is ErrorCode.BACKEND_UNAVAILABLE
            assert error.retryable is False

    async def test_server_side_statuses_are_retryable_upstream_errors(self) -> None:
        error = await self.api_failure(
            HTTPStatus.BAD_GATEWAY,
            "cluster unavailable",
        )
        assert error.code is ErrorCode.UPSTREAM_ERROR
        assert error.retryable is True

    async def test_other_client_statuses_are_not_retryable(self) -> None:
        error = await self.api_failure(
            HTTPStatus.CONFLICT,
            "something else",
        )
        assert error.code is ErrorCode.UPSTREAM_ERROR
        assert error.retryable is False

    async def test_a_successful_block_raises_nothing(self) -> None:
        async with elasticsearch_tool_error_handler("melodi"):
            result = "answer"
        assert result == "answer"
