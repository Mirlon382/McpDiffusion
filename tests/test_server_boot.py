"""The real app, booted in memory -- the layer no test in this repo ever exercised.

`mcpdiffusion.server` reads its settings at import, so this file owns the only import of it:
the environment is pinned first, and a developer's local `.env` cannot change the outcome
because environment variables outrank the dotenv file in pydantic-settings.

This is the CLAUDE.md "Verifying a change" check, kept running: if it is green, the app
factory, the middleware stack, the lifespan and all twelve tools came up.
"""

import importlib
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware
from starlette.applications import Starlette

from tests.conftest import ALL_TOOL_NAMES

SERVER_ENV = {
    "ES_HOST": "http://elasticsearch.invalid:9200",
    "MCP_HOST": "127.0.0.1",
    "MCP_PORT": "8123",
    "ALLOWED_HOSTS": '["mcp.test"]',
    "ALLOWED_ORIGINS": "[]",
    "TRUSTED_PROXY_HOSTS": '["127.0.0.1"]',
    "ENABLE_INSEE_TOOLS": "true",
    "ENABLE_MELODI_TOOLS": "true",
    "ENABLE_RMES_TOOLS": "true",
    "ENABLE_FEEDBACK_TOOL": "true",
    "LOG_LEVEL": "WARNING",
}


@pytest.fixture(scope="module")
def booted() -> Iterator[Any]:
    saved = {name: os.environ.get(name) for name in SERVER_ENV}
    os.environ.update(SERVER_ENV)
    try:
        yield importlib.import_module("mcpdiffusion.server")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestTheAppBoots:
    async def test_the_twelve_tools_come_up_through_the_real_stack(self, booted: Any) -> None:
        async with Client(booted.mcp) as client:
            tools = await client.list_tools()
        assert [tool.name for tool in tools] == ALL_TOOL_NAMES

    def test_the_environment_reaches_the_settings_of_the_running_app(self, booted: Any) -> None:
        assert booted.settings.mcp_port == 8123
        assert booted.settings.allowed_hosts == ["mcp.test"]

    def test_the_middleware_stack_is_ordered_as_the_docs_require(self, booted: Any) -> None:
        # Docs, /servers/middleware: error handling first in (sees the whole chain), logging last.
        classes = [type(middleware) for middleware in booted.mcp.middleware]
        guard = classes[0]  # FastMCP's own DereferenceRefsMiddleware leads any server
        assert classes[1:] == [
            ErrorHandlingMiddleware,
            SlidingWindowRateLimitingMiddleware,
            TimingMiddleware,
            LoggingMiddleware,
        ]
        assert guard.__name__ == "DereferenceRefsMiddleware"

    def test_the_http_app_is_built_with_host_protection_enforced(self, booted: Any) -> None:
        assert isinstance(booted.app, Starlette)

    async def test_a_real_tool_call_runs_end_to_end_without_any_backend(self, booted: Any) -> None:
        # Homepage and feedback need no client and open no socket: the whole in-memory path,
        # middlewares and lifespan included, must work.
        async with Client(booted.mcp) as client:
            homepage = await client.call_tool("get_insee_homepage")
            feedback = await client.call_tool(
                "send_feedback",
                {
                    "author": "test-suite",
                    "feedback": "Booted the real app in memory.",
                },
            )
        assert not homepage.is_error
        assert homepage.structured_content["count"] > 0
        assert not feedback.is_error
        assert feedback.structured_content["status"] == "success"
