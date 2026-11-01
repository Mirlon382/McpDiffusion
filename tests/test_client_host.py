"""The rate-limit key: per-client where the transport says who the client is, shared where it does not."""

from types import SimpleNamespace

import pytest
from diffusion_core import client_host as client_host_module
from diffusion_core.client_host import UNKNOWN_CLIENT, resolve_client_host


def fake_request(host: str | None) -> SimpleNamespace:
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(client=client)


class TestResolveClientHost:
    def test_a_resolved_socket_address_becomes_the_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            client_host_module,
            "get_http_request",
            lambda: fake_request("203.0.113.7"),
        )
        assert resolve_client_host(None) == "203.0.113.7"

    def test_no_http_request_falls_back_to_the_shared_bucket(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raise_runtime_error() -> SimpleNamespace:
            raise RuntimeError("no active request")

        monkeypatch.setattr(
            client_host_module,
            "get_http_request",
            raise_runtime_error,
        )
        assert resolve_client_host(None) == UNKNOWN_CLIENT

    def test_a_request_without_a_peer_falls_back_too(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            client_host_module,
            "get_http_request",
            lambda: fake_request(None),
        )
        assert resolve_client_host(None) == UNKNOWN_CLIENT
