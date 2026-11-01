"""The configuration surface: typed loading, the startup validator, and the docs that must match it."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from mcpdiffusion.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


class TestEnvironmentLoading:
    def test_environment_variables_reach_typed_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ES_HOST", "http://elasticsearch:9200")
        monkeypatch.setenv("MCP_PORT", "9999")
        monkeypatch.setenv("ALLOWED_HOSTS", '["mcp.example.com"]')
        monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "5")
        monkeypatch.setenv("ENABLE_RMES_TOOLS", "false")
        settings = Settings(_env_file=None)
        assert settings.mcp_port == 9999
        assert settings.allowed_hosts == ["mcp.example.com"]
        assert settings.rate_limit_max_requests == 5
        assert settings.enable_rmes_tools is False

    def test_defaults_apply_when_the_environment_is_silent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("MCP_PORT", raising=False)
        monkeypatch.delenv("RATE_LIMIT_MAX_REQUESTS", raising=False)
        settings = Settings(
            _env_file=None,
            es_host="http://elasticsearch:9200",
        )
        assert settings.mcp_port == 8000
        assert settings.rate_limit_max_requests == 100


class TestStartupValidator:
    """ES_HOST is required unless both search families that use it are off -- fail at boot, not on first search."""

    def test_missing_host_with_insee_enabled_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ES_HOST is required"):
            Settings(
                _env_file=None,
                enable_insee_tools=True,
            )

    def test_missing_host_with_both_families_off_is_accepted(self) -> None:
        settings = Settings(
            _env_file=None,
            enable_insee_tools=False,
            enable_melodi_tools=False,
        )
        assert settings.es_host is None

    def test_missing_host_with_rmes_and_feedback_only_is_accepted(self) -> None:
        settings = Settings(
            _env_file=None,
            enable_insee_tools=False,
            enable_melodi_tools=False,
            enable_rmes_tools=True,
            enable_feedback_tool=True,
        )
        assert settings.enable_rmes_tools is True


class TestDocumentedConfigSurface:
    """The example env file is the only description of what this server can be configured with."""

    def test_env_example_names_are_exactly_the_settings_fields(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        documented = set(re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)=", text))
        fields = {name.upper() for name in Settings.model_fields}
        missing = fields - documented
        invented = documented - fields
        assert not missing, f"settings without a documented env var: {sorted(missing)}"
        assert not invented, f"env vars the Settings class does not read: {sorted(invented)}"

    def test_every_settings_field_is_documented_once(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        names = re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)=", text)
        assert len(names) == len(set(names)), "a variable is listed twice in .env.example"
