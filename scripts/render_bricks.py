"""Render the three surfaces that name a brick, from `bricks.yaml`.

    uv run python scripts/render_bricks.py          # rewrite them
    uv run python scripts/render_bricks.py --check  # exit 1 if any of them has drifted

What it renders:

- the brick services between the markers in `docker-compose.yml`;
- `packages/<group>/.env.example`, the configuration surface of that brick alone;
- `deploy/gateway-registry.yaml`, one entry per brick for the gateway's registry.

Two facts are derived from the code rather than repeated here, because they are properties of the
brick and not of its deployment: which variables the brick reads (its `Settings` class, so the
example env file cannot drift from it) and whether the brick needs Elasticsearch at all (whether
that class declares a host).
"""

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BRICKS_YAML = REPO_ROOT / "bricks.yaml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
REGISTRY_FILE = REPO_ROOT / "deploy" / "gateway-registry.yaml"

BEGIN_MARKER = "  # --- BEGIN GENERATED FROM bricks.yaml (scripts/render_bricks.py) ---"
END_MARKER = "  # --- END GENERATED FROM bricks.yaml ---"

GENERATED_NOTICE = "Generated from bricks.yaml -- run `uv run python scripts/render_bricks.py`."

# Width the section rules are drawn to, so the headings line up.
SECTION_WIDTH = 98


def load_bricks() -> dict[str, Any]:
    """The declared metadata, with the settings class and the Elasticsearch need of each brick."""
    declaration = yaml.safe_load(BRICKS_YAML.read_text(encoding="utf-8"))
    for brick in declaration["bricks"]:
        settings = importlib.import_module(f"{brick['group']}_mcp.settings").Settings
        brick["settings"] = settings
        brick["env_file"] = REPO_ROOT / brick["package"] / ".env.example"
        brick["url"] = declaration["url_pattern"].format(name=brick["name"], port=brick["port"])
        brick["needs_elasticsearch"] = "es_host" in settings.model_fields
    return declaration


def render_environment_value(value: Any) -> str:
    """One environment value, as the settings class would read it back."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | dict):
        return json.dumps(value)
    return str(value)


def render_env_example(brick: dict[str, Any], declaration: dict[str, Any]) -> str:
    """The configuration surface of one brick: every variable it reads, with its default."""
    settings = brick["settings"]
    examples: dict[str, str] = declaration.get("environment_examples", {})
    own = set(settings.__annotations__)
    lines = [
        f"# {brick['name']} -- {brick['title']}",
        "#",
        f"# Every variable this brick reads, with the default it falls back to. {declaration['domain']} is",
        "# the domain the whole family is grouped under; the other two bricks are separate processes",
        "# with their own env file. Copy this file to .env next to the process that runs this brick.",
        "#",
        f"# In the compose stack this brick listens on port {brick['port']}; the service sets MCP_PORT",
        "# itself, so the default below only applies to a process started by hand.",
        "#",
        f"# {GENERATED_NOTICE}",
        "",
    ]

    for heading, selected in (("Shared by every brick", False), ("This brick", True)):
        fields = [name for name in settings.model_fields if (name in own) is selected]
        if not fields:
            continue
        lines.append(f"# {heading} " + "-" * (SECTION_WIDTH - len(heading) - 3))
        for name in fields:
            default = settings.model_fields[name].default
            if default is None:
                # No usable default: present as an example, never guessed for the operator.
                lines.append(f"#{name.upper()}={examples.get(name.upper(), '')}")
            else:
                lines.append(f"{name.upper()}={render_environment_value(default)}")
        lines.append("")

    if brick["needs_elasticsearch"]:
        lines.append(
            "# ES_HOST has no default on purpose: this brick answers its search tools from the INSEE\n"
            "# Elasticsearch indices, so it refuses to start without one."
        )
    else:
        lines.append(
            "# This brick declares no Elasticsearch host: it answers over SPARQL alone and starts with\n"
            "# no infrastructure behind it."
        )
    return "\n".join(lines) + "\n"


def render_compose_services(declaration: dict[str, Any]) -> str:
    """The compose services for the bricks, between the markers in docker-compose.yml."""
    lines = [BEGIN_MARKER]
    for brick in declaration["bricks"]:
        lines += [
            f"  # {brick['title']} -- {brick['url']}",
            f"  {brick['name']}:",
            "    build:",
            "      context: .",
            "      dockerfile: Dockerfile",
            f"      target: {brick['name']}",
            f"    image: {brick['name']}:local",
        ]
        if brick["needs_elasticsearch"]:
            lines += [
                "    depends_on:",
                "      es-restore:",
                "        condition: service_completed_successfully",
            ]
        lines += [
            "    env_file:",
            "      - .env",
            "    environment:",
            "      # Listen on every interface: the container's loopback is not reachable from the host.",
            "      MCP_HOST: 0.0.0.0",
            f"      MCP_PORT: {brick['port']}",
        ]
        if brick["needs_elasticsearch"]:
            lines += [
                "      # Defaults to the service above; an ES_HOST in your .env wins.",
                "      ES_HOST: ${ES_HOST:-http://elasticsearch:9200}",
            ]
        lines += [
            "    ports:",
            f'      - "{brick["port"]}:{brick["port"]}"',
            "",
        ]
    lines.append(END_MARKER)
    return "\n".join(lines)


def render_registry_fragment(declaration: dict[str, Any]) -> str:
    """One gateway registry entry per brick, in the gateway's registry schema."""
    entries = {
        "servers": [
            {
                "name": brick["namespace"],
                "url": brick["url"],
                "transport": "http",
                "domain": declaration["domain"],
                "description": brick["description"],
                "tags": brick["tags"],
                "enabled": True,
            }
            for brick in declaration["bricks"]
        ],
    }
    header = (
        "# The gateway's registry fragment for the three bricks.\n"
        "#\n"
        "# Names are gateway namespaces; URLs retain the Docker Compose service hosts.\n"
        f"# {GENERATED_NOTICE}\n\n"
    )
    return header + yaml.safe_dump(entries, sort_keys=False, allow_unicode=True)


def render_compose_file(current: str, services: str) -> str:
    """`docker-compose.yml` with the generated block replaced."""
    start = current.index(BEGIN_MARKER)
    end = current.index(END_MARKER) + len(END_MARKER)
    return f"{current[:start]}{services}{current[end:]}"


def write_or_check(path: Path, content: str, drifted: list[Path]) -> None:
    """Write `content`, or record the path when it is missing or already differs."""
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    drifted.append(path)
    if not CHECK_ONLY:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


CHECK_ONLY = False


def main() -> int:
    global CHECK_ONLY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    arguments = parser.parse_args()
    CHECK_ONLY = arguments.check

    declaration = load_bricks()
    drifted: list[Path] = []

    for brick in declaration["bricks"]:
        write_or_check(
            brick["env_file"],
            render_env_example(brick, declaration),
            drifted,
        )

    write_or_check(
        REGISTRY_FILE,
        render_registry_fragment(declaration),
        drifted,
    )
    write_or_check(
        COMPOSE_FILE,
        render_compose_file(
            COMPOSE_FILE.read_text(encoding="utf-8"),
            render_compose_services(declaration),
        ),
        drifted,
    )

    for path in drifted:
        print(f"{'drifted' if CHECK_ONLY else 'wrote'} {path.relative_to(REPO_ROOT)}")
    if not drifted:
        print("every rendered file is up to date")
    return 1 if (CHECK_ONLY and drifted) else 0


if __name__ == "__main__":
    sys.exit(main())
