"""The HTTP-server and policy settings every diffusion brick shares.

A brick subclasses this and adds only its own source's fields. The field names fix the
environment variable names (pydantic-settings uppercases them), so they are the settings
surface documented in `.env.example`, compose and k8s — changing one here changes what
every brick reads.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    # HTTP server ------------------------------------------------------------------------------------------------------
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    # JSON list of the hostnames clients use to reach this server, checked against the Host
    # header. "*" accepts any host, which disables the check.
    allowed_hosts: list[str] = ["*"]
    # JSON list of browser origins allowed to call the server. Empty rejects every cross-origin
    # browser request, which is right until a browser-based client needs in.
    allowed_origins: list[str] = []
    # Peers whose X-Forwarded-For header is believed; anything else keeps its real socket address.
    # Accepts addresses, CIDR networks and literals. Widening this lets callers forge their own address.
    trusted_proxy_hosts: list[str] = ["127.0.0.1"]

    # Rate limiting ----------------------------------------------------------------------------------------------------
    # Per brick, not per family (split decision 3): each brick process gets its own bucket.
    rate_limit_max_requests: int = 100
    rate_limit_window_minutes: int = 1

    # Logging ----------------------------------------------------------------------------------------------------------
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
