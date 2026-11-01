"""The HTTP-server and policy settings every diffusion brick shares.

A brick subclasses this and adds only its own source's fields. The field names fix the
environment variable names (pydantic-settings uppercases them), so they are the settings
surface documented in `.env.example`, compose and k8s — changing one here changes what
every brick reads.
"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseSettings):
    # HTTP server ------------------------------------------------------------------------------------------------------
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    # Bound backend probes so readiness checks cannot hang on an unavailable upstream.
    health_probe_timeout_seconds: int = Field(default=5, gt=0)
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


class ElasticsearchServerSettings(ServerSettings):
    """`ServerSettings` plus the connection to the Elasticsearch cluster.

    The two bricks that search Elasticsearch (insee.fr and MELODI) declare these four fields
    identically, so they live here. Index names do NOT: which index a source reads belongs to
    that source's brick.

    `ES_HOST` is required by the two bricks that search Elasticsearch; RMES does not use it.
    """

    # Only the search tools read Elasticsearch; a SPARQL-only brick never declares this field.
    es_host: str | None = None
    # Elasticsearch is often internal with a self-signed certificate.
    es_tls_verify: bool = True
    es_request_timeout_seconds: int = 30
    # Retries the client makes itself before a search fails. Raising it hides brief outages;
    # lowering it surfaces them sooner.
    es_max_retries: int = 2

    def requires_elasticsearch_host(self) -> bool:
        """Whether this server is unanswerable without an Elasticsearch host.

        True by definition for a brick built on this class; the aggregate says otherwise when
        both Elasticsearch families are switched off.
        """
        return True

    def missing_elasticsearch_host_message(self) -> str:
        """The startup error a caller sees when `ES_HOST` is absent but needed."""
        return "ES_HOST is required: this server answers its tools from the INSEE Elasticsearch indices. Set it."

    @model_validator(mode="after")
    def require_elasticsearch_host(self) -> "ElasticsearchServerSettings":
        """Fail at startup rather than on the first search that needs a host."""
        if self.es_host is None and self.requires_elasticsearch_host():
            raise ValueError(self.missing_elasticsearch_host_message())
        return self
