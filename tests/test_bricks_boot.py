"""Each brick, on its own -- the check that proves a brick is a brick.

Three properties, each of which the split could break silently:

- it starts and publishes exactly its own tools, whatever else is installed;
- it imports no sibling brick;
- nothing it sends a client -- a tool description or the handshake -- names a tool it does not have.

`rmes` is held to the stronger claim the split is built on: it needs no infrastructure at all.
"""

import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from pydantic import ValidationError

from tests.conftest import BRICK_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]

# A host that cannot resolve: the validators demand one, and no test here dials it.
FAKE_ELASTICSEARCH_HOST = "http://elasticsearch.invalid:9200"

BRICK_ENVIRONMENT = {
    "MCP_HOST": "127.0.0.1",
    "ALLOWED_HOSTS": '["brick.test"]',
    "LOG_LEVEL": "WARNING",
}

# Where each brick lives, what serves it, and whether it may start without Elasticsearch.
BRICKS: dict[str, dict[str, Any]] = {
    "insee": {
        "server_module": "insee_mcp.server",
        "settings_module": "insee_mcp.settings",
        "package": REPO_ROOT / "packages" / "insee" / "src" / "insee_mcp",
        "uses_elasticsearch": True,
    },
    "melodi": {
        "server_module": "melodi_mcp.server",
        "settings_module": "melodi_mcp.settings",
        "package": REPO_ROOT / "packages" / "melodi" / "src" / "melodi_mcp",
        "uses_elasticsearch": True,
    },
    "rmes": {
        "server_module": "rmes_mcp.server",
        "settings_module": "rmes_mcp.settings",
        "package": REPO_ROOT / "packages" / "rmes" / "src" / "rmes_mcp",
        "uses_elasticsearch": False,
    },
}

# Dependencies a brick that only speaks HTTP must never reach, whatever its group declares.
INFRASTRUCTURE_MODULES = ("elasticsearch", "elastic_transport", "bs4", "lxml", "trafilatura")

# Runs in a fresh interpreter: proves the brick starts with no host in the environment at all.
RMES_BOOT_PROBE = """
import asyncio

from fastmcp import Client

from rmes_mcp import server


async def main() -> None:
    async with Client(server.mcp) as client:
        names = [tool.name for tool in await client.list_tools()]
    print(len(names), names)


asyncio.run(main())
"""

_BOOTED: dict[str, Any] = {}


def brick_server(family: str) -> Any:
    """Import a brick's server module with the environment that brick needs -- once per session.

    A server module reads its settings at import, so the environment has to be pinned *before* the
    import, and only the first import is the one that reads it.
    """
    if family in _BOOTED:
        return _BOOTED[family]

    saved = {name: os.environ.get(name) for name in (*BRICK_ENVIRONMENT, "ES_HOST")}
    os.environ.update(BRICK_ENVIRONMENT)
    if BRICKS[family]["uses_elasticsearch"]:
        os.environ["ES_HOST"] = FAKE_ELASTICSEARCH_HOST
    else:
        os.environ.pop("ES_HOST", None)
    try:
        _BOOTED[family] = importlib.import_module(BRICKS[family]["server_module"])
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return _BOOTED[family]


async def published_tools(family: str) -> list[Any]:
    """The tools one brick publishes, through an in-memory `Client` and its own middleware chain."""
    async with Client(brick_server(family).mcp) as client:
        return list(await client.list_tools())


def foreign_tool_names(family: str) -> set[str]:
    """Every tool name that belongs to another brick."""
    return {name for other_family, names in BRICK_TOOL_NAMES.items() if other_family != family for name in names}


def imported_module_names(package: Path) -> list[tuple[Path, str]]:
    """Every module a package imports by name, with the file that imports it."""
    imports: list[tuple[Path, str]] = []
    for path in sorted(package.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*(?:from|import)\s+([A-Za-z_][\w.]*)", line)
            if match:
                imports.append((path, match.group(1).split(".")[0]))
    return imports


class TestABrickAlone:
    """One brick, one process, one dependency group: the lego property of the split."""

    @pytest.mark.parametrize("family", sorted(BRICKS))
    async def test_a_brick_publishes_exactly_its_own_tools(self, family: str) -> None:
        assert [tool.name for tool in await published_tools(family)] == BRICK_TOOL_NAMES[family]

    @pytest.mark.parametrize("family", sorted(BRICKS))
    async def test_a_brick_publishes_no_feedback_tool(self, family: str) -> None:
        # Decision 2: feedback belongs to the gateway, never to a brick.
        assert "send_feedback" not in [tool.name for tool in await published_tools(family)]

    @pytest.mark.parametrize("family", sorted(BRICKS))
    async def test_every_tool_description_names_only_tools_this_brick_has(self, family: str) -> None:
        # Decision 5: the cross-server routing prose moved to the gateway, so a brick mentioning a
        # sibling's tool would send a client after something it cannot have.
        foreign = foreign_tool_names(family)
        # SDK v2 renamed the schema fields to snake_case; the camelCase bridge only warns.
        published = "\n".join(
            f"{tool.name}\n{tool.description}\n{json.dumps(tool.input_schema)}\n{json.dumps(tool.output_schema)}"
            for tool in await published_tools(family)
        )
        mentioned = sorted(name for name in foreign if name in published)
        assert not mentioned, f"{family} names tools it does not publish: {mentioned}"

    @pytest.mark.parametrize("family", sorted(BRICKS))
    def test_the_handshake_describes_only_this_brick(self, family: str) -> None:
        instructions = importlib.import_module(f"{family}_mcp.instructions").INSTRUCTIONS
        mentioned = sorted(name for name in foreign_tool_names(family) if name in instructions)
        assert not mentioned, f"the {family} handshake names tools it does not publish: {mentioned}"
        assert "three sources" not in instructions


class TestABrickKnowsNoSibling:
    """A brick imports the core and itself. No other server package is available to it."""

    @pytest.mark.parametrize("family", sorted(BRICKS))
    def test_a_brick_imports_no_other_server_package(self, family: str) -> None:
        # The sibling bricks, and the aggregate too: a brick that imported the assembly would stop
        # being independently deployable.
        foreign_packages = {f"{other}_mcp" for other in BRICKS if other != family} | {"mcpdiffusion"}
        offenders = [
            (path.relative_to(REPO_ROOT), module)
            for path, module in imported_module_names(BRICKS[family]["package"])
            if module in foreign_packages
        ]
        assert not offenders, f"{family} imports another server package: {offenders}"


class TestRmesNeedsNoInfrastructure:
    """The claim the dependency split exists for: a brick with no backend to connect to."""

    def test_the_rmes_brick_declares_no_elasticsearch_host(self) -> None:
        settings = importlib.import_module(BRICKS["rmes"]["settings_module"]).Settings
        assert "es_host" not in settings.model_fields

    @pytest.mark.parametrize("family", ["insee", "melodi"])
    def test_a_searching_brick_refuses_to_start_without_a_host(self, family: str) -> None:
        settings = importlib.import_module(BRICKS[family]["settings_module"]).Settings
        with pytest.raises(ValidationError, match="ES_HOST is required"):
            settings(
                _env_file=None,
                es_host=None,
            )

    def test_the_rmes_brick_boots_in_a_process_with_no_elasticsearch_host(self) -> None:
        environment = {name: value for name, value in os.environ.items() if name != "ES_HOST"}
        environment["LOG_LEVEL"] = "WARNING"
        result = subprocess.run(
            [sys.executable, "-c", RMES_BOOT_PROBE],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "3 ['search_rmes_graphs', 'describe_rmes_resource', 'run_rmes_sparql']"

    def test_no_rmes_module_reaches_infrastructure_it_does_not_declare(self) -> None:
        offenders = [
            (path.relative_to(REPO_ROOT), module)
            for path, module in imported_module_names(BRICKS["rmes"]["package"])
            if module in INFRASTRUCTURE_MODULES
        ]
        assert not offenders, f"the rmes brick imports infrastructure: {offenders}"
