"""Compose the in-process aggregate from the three independent MCP servers."""

import asyncio
from collections.abc import Sequence
from typing import Any

from diffusion_core import McpApplication
from diffusion_core.settings import ServerSettings
from fastmcp import FastMCP
from insee_mcp.server import application as insee_application
from melodi_mcp.server import application as melodi_application
from rmes_mcp.server import application as rmes_application

type Brick = tuple[FastMCP[Any], str, str]
BRICK_APPLICATIONS: tuple[McpApplication[Any], ...] = (
    insee_application,
    melodi_application,
    rmes_application,
)
BRICKS: tuple[Brick, ...] = (
    (
        insee_application.mcp,
        "insee.fr -- publications, rapid releases and headline indicators",
        "a document URL or publication id",
    ),
    (
        melodi_application.mcp,
        "MELODI -- the dataset catalogue and observations",
        "a dataset id or modality code",
    ),
    (
        rmes_application.mcp,
        "RMES -- statistical metadata: definitions and nomenclatures. It holds no figures",
        "a graph URI",
    ),
)


def build_instructions(bricks: Sequence[Brick]) -> str:
    """Keep the aggregate handshake aligned with the servers it actually mounts."""
    source_descriptions = "\n".join(f"- {description}" for _, description, _ in bricks)
    identifiers = ", ".join(identifier for _, _, identifier in bricks)
    discovery_rule = (
        f"- Never guess {identifiers}. Each is opaque and must come from a discovery call first.\n"
        if identifiers
        else ""
    )
    sections = [
        "This server exposes INSEE (French national statistics) data through these sources:",
        source_descriptions,
        "Rules that apply to every tool:",
    ]
    if discovery_rule:
        sections.append(discovery_rule.rstrip())
    sections.extend(
        [
            "- The data is French. Search with French keywords and rich synonyms.",
            "- An empty result is a valid answer, not a failure. It usually means the filters were too narrow.",
        ]
    )
    return "\n\n".join(section for section in sections if section)


async def aggregate_health_check(_context: Any | None) -> dict[str, bool]:
    """Probe every mounted brick and key each dependency by its owning server."""
    statuses_by_brick = await asyncio.gather(*(application.health_statuses() for application in BRICK_APPLICATIONS))
    return {
        f"{application.name}.{backend}": ready
        for application, statuses in zip(BRICK_APPLICATIONS, statuses_by_brick, strict=True)
        for backend, ready in statuses.items()
    }


def mount_bricks(
    aggregate: FastMCP[Any],
    bricks: Sequence[Brick] = BRICKS,
) -> None:
    """Mount each brick live without a namespace so its documented tool names stay unchanged."""
    for server, _, _ in bricks:
        aggregate.mount(server, namespace=None)


def register_bricks(aggregate: FastMCP[Any], _settings: ServerSettings) -> None:
    """Factory callback: this aggregate serves the fixed three-brick composition."""
    mount_bricks(aggregate)
