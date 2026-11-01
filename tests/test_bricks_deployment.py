"""The deployment surface follows bricks.yaml, and stays buildable.

`docker compose up` needs a daemon this repo's test environment does not have, so what is checked
here is the part that can be checked anywhere: that the rendered artifacts still match their single
source of truth, that each brick has both a compose service and a Dockerfile target, and that the
target building the image CI publishes is still the default one.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import BRICK_TOOL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[1]
BRICKS_YAML = REPO_ROOT / "bricks.yaml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "Dockerfile"
RENDERER = REPO_ROOT / "scripts" / "render_bricks.py"

STAGE_LINE = re.compile(r"^FROM\s+\S+\s+AS\s+(?P<stage>\S+)\s*$")
COMMAND_LINE = re.compile(r"^CMD\s+\[(?P<arguments>.*)\]$")


def declared_bricks() -> list[dict[str, Any]]:
    return yaml.safe_load(BRICKS_YAML.read_text(encoding="utf-8"))["bricks"]


def compose_services() -> dict[str, dict[str, Any]]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


def dockerfile_stages() -> list[str]:
    """The stage names of the Dockerfile, in file order -- the last one is the default target."""
    return [
        match.group("stage")
        for match in (STAGE_LINE.match(line) for line in DOCKERFILE.read_text(encoding="utf-8").splitlines())
        if match is not None
    ]


def stage_commands() -> dict[str, str]:
    """The CMD each stage declares, keyed by stage name."""
    commands: dict[str, str] = {}
    current_stage = ""
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stage = STAGE_LINE.match(line)
        if stage is not None:
            current_stage = stage.group("stage")
            continue
        command = COMMAND_LINE.match(line)
        if command is not None and current_stage:
            commands[current_stage] = command.group("arguments")
    return commands


class TestTheSingleSourceOfTruth:
    """bricks.yaml is what the compose services, the env examples and the registry are rendered from."""

    def test_the_rendered_artifacts_are_up_to_date(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RENDERER), "--check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize("brick", declared_bricks(), ids=lambda brick: brick["name"])
    def test_every_brick_ships_an_example_env_file_naming_it(self, brick: dict[str, Any]) -> None:
        text = (REPO_ROOT / brick["package"] / ".env.example").read_text(encoding="utf-8")
        assert text.startswith(f"# {brick['name']}")
        assert "MCP_PORT=" in text

    def test_the_registry_fragment_lists_gateway_namespaces_and_brick_tags(self) -> None:
        registry = yaml.safe_load((REPO_ROOT / "deploy" / "gateway-registry.yaml").read_text(encoding="utf-8"))
        expected = {
            "insee": ["insee", "publications", "rapid-releases", "key-figures", "homepage-indicators"],
            "melodi": ["insee", "melodi", "datasets", "modalities", "observations"],
            "rmes": ["insee", "rmes", "metadata", "definitions", "nomenclatures", "classifications", "sparql"],
        }
        assert [entry["name"] for entry in registry["servers"]] == list(expected)
        assert {entry["name"]: entry["tags"] for entry in registry["servers"]} == expected

    def test_the_registry_fragment_matches_the_gateway_server_entry_contract(self) -> None:
        registry = yaml.safe_load((REPO_ROOT / "deploy" / "gateway-registry.yaml").read_text(encoding="utf-8"))
        gateway_entry_fields = {
            "name",
            "url",
            "transport",
            "domain",
            "description",
            "tags",
            "enabled",
            "timeout",
            "max_concurrency",
            "cache_ttl",
        }
        assert set(registry) == {"servers"}
        expected_urls = {
            "insee": "http://insee-mcp:8001/mcp",
            "melodi": "http://melodi-mcp:8002/mcp",
            "rmes": "http://rmes-mcp:8003/mcp",
        }
        assert {entry["name"]: entry["url"] for entry in registry["servers"]} == expected_urls
        for entry in registry["servers"]:
            assert {"name", "url", "domain"} <= set(entry)
            assert set(entry) <= gateway_entry_fields
            assert entry["domain"] == "Insee"
            assert entry["transport"] == "http"
            assert entry["enabled"] is True


class TestTheComposeStack:
    """Three bricks, one service each, plus the cluster two of them answer from."""

    @pytest.mark.parametrize("brick", declared_bricks(), ids=lambda brick: brick["name"])
    def test_every_brick_has_a_service_built_from_its_own_target(self, brick: dict[str, Any]) -> None:
        service = compose_services()[brick["name"]]
        assert service["build"]["target"] == brick["name"]
        assert service["environment"]["MCP_PORT"] == brick["port"]
        assert service["ports"] == [f"{brick['port']}:{brick['port']}"]

    def test_elasticsearch_and_the_aggregate_are_still_in_the_stack(self) -> None:
        services = compose_services()
        assert {"elasticsearch", "mcpdiffusion", "inspector"} <= set(services)

    def test_a_brick_without_elasticsearch_does_not_wait_for_the_restore(self) -> None:
        services = compose_services()
        assert "depends_on" not in services["rmes-mcp"]
        assert "depends_on" in services["insee-mcp"]

    def test_every_service_reads_the_documented_env_file(self) -> None:
        for brick in declared_bricks():
            assert compose_services()[brick["name"]]["env_file"] == [".env"]
        assert (REPO_ROOT / ".env.example").exists()


class TestTheDockerfile:
    """One file, one target per brick, and the aggregate still built by an untargeted build."""

    @pytest.mark.parametrize("brick", declared_bricks(), ids=lambda brick: brick["name"])
    def test_every_brick_has_a_target_running_its_own_module(self, brick: dict[str, Any]) -> None:
        assert brick["name"] in dockerfile_stages()
        assert stage_commands()[brick["name"]] == f'"python", "-m", "{brick["group"]}_mcp.server"'

    def test_the_last_stage_is_the_aggregate_so_ci_keeps_building_it(self) -> None:
        # `docker build` without --target builds the last stage, and CI passes no target.
        assert dockerfile_stages()[-1] == "mcpdiffusion"
        assert stage_commands()["mcpdiffusion"] == '"python", "-m", "mcpdiffusion.server"'

    def test_every_brick_target_syncs_only_its_own_dependency_group(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        for brick in declared_bricks():
            assert f"uv sync --no-dev --locked --package {brick['name']}" in text

    def test_every_brick_group_is_a_real_tool_family(self) -> None:
        # The compose service name, the package directory and the tool family all line up.
        for brick in declared_bricks():
            assert brick["group"] in BRICK_TOOL_NAMES
