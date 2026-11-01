"""Every value the RMES brick can be configured with.

The HTTP-server, rate-limit and logging fields come from the core's `ServerSettings`. This brick
declares no Elasticsearch host: RMES is read over SPARQL, so the brick starts with no
infrastructure behind it at all.
"""

from diffusion_core.settings import ServerSettings


class Settings(ServerSettings):
    """The RMES brick's settings: the shared server block plus the SPARQL endpoint it queries."""

    # Where queries are POSTed. RMES takes its timeout per query, from the tool's own input.
    rmes_sparql_endpoint_url: str = "https://rdf.insee.fr/sparql"
    # Not an address to call: the namespace every named graph URI starts with, stripped off
    # before a graph is matched against a family.
    rmes_graph_base_uri: str = "http://rdf.insee.fr/graphes/"
    # Listing every graph counts triples across the whole store, so it gets its own budget.
    rmes_graph_listing_timeout_seconds: float = 45.0
    rmes_graph_listing_max_rows: int = 1000
    rmes_graph_cache_ttl_seconds: float = 3600.0


def load_settings() -> Settings:
    return Settings()
