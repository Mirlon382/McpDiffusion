"""HTTP-level tests for readiness and liveness routes produced by the shared factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from diffusion_core import create_server
from diffusion_core.settings import ServerSettings
from starlette.testclient import TestClient


@pytest.mark.parametrize(("backend_ready", "expected_status"), [(True, 200), (False, 503)])
def test_health_route_reports_identity_and_backend_readiness_without_addresses(
    backend_ready: bool,
    expected_status: int,
) -> None:
    @asynccontextmanager
    async def lifespan(_server: Any) -> AsyncIterator[dict[str, bool]]:
        yield {"backend_ready": backend_ready}

    async def health_check(context: Any | None) -> dict[str, bool]:
        return {"elasticsearch": bool(context and context["backend_ready"])}

    application = create_server(
        name="test-mcp",
        version="9.8.7",
        instructions="test server",
        lifespan=lifespan,
        health_check=health_check,
        register=lambda _mcp, _settings: None,
        settings=ServerSettings(_env_file=None, allowed_hosts=["health.test"]),
    )

    with TestClient(application.app) as client:
        response = client.get("/health", headers={"Host": "health.test"})

    assert response.status_code == expected_status
    assert response.json() == {
        "name": "test-mcp",
        "version": "9.8.7",
        "status": "ready" if backend_ready else "unavailable",
        "backends": {"elasticsearch": "ready" if backend_ready else "unavailable"},
    }
    assert "health.test" not in response.text
    assert "localhost" not in response.text


def test_liveness_is_independent_of_backend_readiness() -> None:
    @asynccontextmanager
    async def lifespan(_server: Any) -> AsyncIterator[dict[str, bool]]:
        yield {"backend_ready": False}

    async def health_check(context: Any | None) -> dict[str, bool]:
        return {"elasticsearch": bool(context and context["backend_ready"])}

    application = create_server(
        name="test-mcp",
        version="9.8.7",
        instructions="test server",
        lifespan=lifespan,
        health_check=health_check,
        register=lambda _mcp, _settings: None,
        settings=ServerSettings(_env_file=None, allowed_hosts=["health.test"]),
    )

    with TestClient(application.app) as client:
        response = client.get("/health/live", headers={"Host": "health.test"})

    assert response.status_code == 200
    assert response.json() == {"name": "test-mcp", "version": "9.8.7", "status": "ok"}


def test_aggregate_health_route_reports_every_mounted_brick() -> None:
    child_applications = []
    for child_name in ("insee-mcp", "rmes-mcp"):

        @asynccontextmanager
        async def child_lifespan(_server: Any, name: str = child_name) -> AsyncIterator[dict[str, str]]:
            yield {"opened_by": name}

        async def child_health(context: Any | None, name: str = child_name) -> dict[str, bool]:
            return {"backend": bool(context and context["opened_by"] == name)}

        child_applications.append(
            create_server(
                name=child_name,
                version="1.2.3",
                instructions="child",
                lifespan=child_lifespan,
                health_check=child_health,
                register=lambda _mcp, _settings: None,
                settings=ServerSettings(_env_file=None, allowed_hosts=["health.test"]),
            )
        )

    async def aggregate_health(_context: Any | None) -> dict[str, bool]:
        statuses = await asyncio.gather(*(application.health_statuses() for application in child_applications))
        return {
            f"{application.name}.backend": ready
            for application, backend_statuses in zip(child_applications, statuses, strict=True)
            for ready in backend_statuses.values()
        }

    def mount_children(mcp: Any, _settings: ServerSettings) -> None:
        for application in child_applications:
            mcp.mount(application.mcp, namespace=None)

    aggregate = create_server(
        name="aggregate",
        version="2.0.0",
        instructions="aggregate",
        lifespan=None,
        health_check=aggregate_health,
        register=mount_children,
        settings=ServerSettings(_env_file=None, allowed_hosts=["health.test"]),
    )

    with TestClient(aggregate.app) as client:
        response = client.get("/health", headers={"Host": "health.test"})

    assert response.status_code == 200
    assert response.json() == {
        "name": "aggregate",
        "version": "2.0.0",
        "status": "ready",
        "backends": {
            "insee-mcp.backend": "ready",
            "rmes-mcp.backend": "ready",
        },
    }
