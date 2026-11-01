"""The real aggregate app, booted in memory and listing its mounted brick tools."""

import importlib
import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware
from starlette.applications import Starlette

from tests.conftest import ALL_TOOL_NAMES

# The aggregate's effective environment in the Compose deployment. Elasticsearch is a
# hostname only inside the Compose network; starting the client does not connect to it.
SERVER_ENV = {
    "ES_HOST": "http://elasticsearch:9200",
    "MCP_HOST": "0.0.0.0",
    "MCP_PORT": "8000",
    "ALLOWED_HOSTS": '["*"]',
    "ALLOWED_ORIGINS": "[]",
    "TRUSTED_PROXY_HOSTS": '["127.0.0.1"]',
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


@pytest.fixture
def composition(booted: Any) -> Any:
    return importlib.import_module("mcpdiffusion.assembly")


class TestTheAppBoots:
    async def test_the_eleven_mounted_tools_come_up_through_the_real_stack(self, booted: Any) -> None:
        async with Client(booted.mcp) as client:
            tools = await client.list_tools()
        assert [tool.name for tool in tools] == ALL_TOOL_NAMES

    def test_aggregate_instructions_have_uniform_markdown_indentation(self, booted: Any) -> None:
        instructions = booted.mcp.instructions
        assert instructions is not None
        assert all(not line.startswith(" ") for line in instructions.splitlines())
        assert "- insee.fr" in instructions
        assert "- MELODI" in instructions
        assert "- RMES" in instructions
        assert "graph URI" in instructions

    def test_the_environment_reaches_the_settings_of_the_running_app(self, booted: Any) -> None:
        assert booted.settings.mcp_host == "0.0.0.0"
        assert booted.settings.mcp_port == 8000
        assert booted.settings.allowed_hosts == ["*"]
        assert booted.settings.allowed_origins == []
        assert booted.settings.trusted_proxy_hosts == ["127.0.0.1"]

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

    async def test_a_real_brick_tool_call_runs_end_to_end(self, booted: Any) -> None:
        async with Client(booted.mcp) as client:
            homepage = await client.call_tool("get_insee_homepage")
        assert not homepage.is_error
        assert homepage.structured_content["count"] > 0

    async def test_omitting_a_brick_removes_only_its_tools_and_guidance(
        self,
        booted: Any,
        composition: Any,
    ) -> None:
        bricks = composition.BRICKS[:-1]
        subset = FastMCP(
            "subset",
            instructions=composition.build_instructions(bricks),
        )
        composition.mount_bricks(subset, bricks)

        async with Client(subset) as client:
            published_names = [tool.name for tool in await client.list_tools()]

        assert published_names == ALL_TOOL_NAMES[:-3]
        instructions = composition.build_instructions(bricks)
        assert "RMES" not in instructions
        assert "graph URI" not in instructions
