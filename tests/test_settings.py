"""The configuration surface shared by the aggregate and its three mounted bricks."""

import re
from pathlib import Path

import pytest
from insee_mcp.settings import Settings as InseeSettings
from melodi_mcp.settings import Settings as MelodiSettings
from rmes_mcp.settings import Settings as RmesSettings

from mcpdiffusion.settings import Settings as AggregateSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SETTING_TYPES = (AggregateSettings, InseeSettings, MelodiSettings, RmesSettings)


class TestEnvironmentLoading:
    def test_environment_variables_reach_aggregate_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MCP_PORT", "9999")
        monkeypatch.setenv("ALLOWED_HOSTS", '["mcp.example.com"]')
        monkeypatch.setenv("RATE_LIMIT_MAX_REQUESTS", "5")
        settings = AggregateSettings(_env_file=None)
        assert settings.mcp_port == 9999
        assert settings.allowed_hosts == ["mcp.example.com"]
        assert settings.rate_limit_max_requests == 5


def all_settings_fields() -> set[str]:
    """All settings exposed by the aggregate's runtime tree."""
    return {field for settings_type in SETTING_TYPES for field in settings_type.model_fields}


class TestDocumentedConfigSurface:
    """Every setting read by any mounted server is documented once in the example env file."""

    def test_env_example_names_are_exactly_the_union_of_settings_fields(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        documented = set(re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)=", text))
        fields = {name.upper() for name in all_settings_fields()}
        missing = fields - documented
        invented = documented - fields
        assert not missing, f"settings without a documented env var: {sorted(missing)}"
        assert not invented, f"env vars no server in the aggregate reads: {sorted(invented)}"

    def test_every_settings_field_is_documented_once(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        names = re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]*)=", text)
        assert len(names) == len(set(names)), "a variable is listed twice in .env.example"
