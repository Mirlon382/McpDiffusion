"""The Elasticsearch client factory and the single place its failures become caller-actionable errors.

Lives behind the `elasticsearch` extra: only a brick that searches Elasticsearch installs the
driver, opens the client, or imports this module. The core itself never does.

Two disjoint exception families reach the translator, and both have to be named:

- `elastic_transport.TransportError` -- the request never got a usable answer (refused, timed
  out, TLS, unparseable). `ConnectionError` and `ConnectionTimeout` are subclasses.
- `elasticsearch.ApiError` -- Elasticsearch answered, with an error status. `NotFoundError`
  (a missing index) and `BadRequestError` are subclasses.

`ApiError` does not inherit from `TransportError`, so catching one never catches the other.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus

from elasticsearch import ApiError, AsyncElasticsearch, TransportError

from .errors import AppToolError, ErrorCode

logger = logging.getLogger(__name__)


def elasticsearch_client(
    host: str,
    tls_verify: bool,
    request_timeout_seconds: int,
    max_retries: int,
) -> AsyncElasticsearch:
    """Return an unconnected client for `host`. Construction opens no connection, so a wrong
    host surfaces on the first search, not here."""
    return AsyncElasticsearch(
        host,
        verify_certs=tls_verify,
        request_timeout=request_timeout_seconds,
        max_retries=max_retries,
        retry_on_timeout=True,
    )


@asynccontextmanager
async def elasticsearch_lifespan(
    host: str,
    tls_verify: bool,
    request_timeout_seconds: int,
    max_retries: int,
) -> AsyncIterator[AsyncElasticsearch]:
    """Open the shared client and close it on shutdown."""
    client = elasticsearch_client(
        host=host,
        tls_verify=tls_verify,
        request_timeout_seconds=request_timeout_seconds,
        max_retries=max_retries,
    )
    logger.info("Elasticsearch client initialized for %s", host)
    try:
        yield client
    finally:
        await client.close()


@asynccontextmanager
async def elasticsearch_tool_error_handler(backend_label: str) -> AsyncIterator[None]:
    """Translate a failed Elasticsearch search into an `AppToolError` naming the backend.

    Wraps the `await` rather than performing it, so it fits both the DSL and the raw client.
    Only the short error type is quoted: the full body belongs in the server log, not in a
    message sent to the caller.
    """
    try:
        yield
    except TransportError as exc:
        # Only the exception type, never its message: with retries enabled the message carries
        # the host and port, and that must not leave the process. The full cause, host included,
        # is in the server log via ErrorHandlingMiddleware.
        raise AppToolError(
            ErrorCode.BACKEND_UNAVAILABLE,
            f"{backend_label} search backend unreachable ({type(exc).__name__}). Verify ES_HOST and try again.",
            retryable=True,
        )
    except ApiError as exc:
        status = exc.status_code
        if status == HTTPStatus.NOT_FOUND:
            raise AppToolError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"The {backend_label} index is missing from Elasticsearch ({exc.error}). "
                "The index is not loaded on the server, so no query against it can succeed. "
                "Rephrasing will not help -- report this instead of retrying.",
            )
        if status == HTTPStatus.BAD_REQUEST:
            raise AppToolError(
                ErrorCode.INVALID_QUERY,
                f"Elasticsearch rejected the {backend_label} search as malformed "
                f"({exc.error}). This is a defect in the server's query, not in the arguments "
                "you passed. Report it instead of retrying.",
            )
        if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise AppToolError(
                ErrorCode.BACKEND_UNAVAILABLE,
                f"Elasticsearch refused the {backend_label} search ({exc.error}). The server's "
                "credentials are missing or insufficient. Report it instead of retrying.",
            )
        raise AppToolError(
            ErrorCode.UPSTREAM_ERROR,
            f"Elasticsearch returned HTTP {status} for the {backend_label} search ({exc.error}).",
            retryable=status >= HTTPStatus.INTERNAL_SERVER_ERROR,
        )
