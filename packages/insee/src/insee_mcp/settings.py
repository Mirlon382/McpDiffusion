"""Every value the insee.fr brick can be configured with.

The HTTP-server, rate-limit and logging fields come from the core's `ServerSettings`, the
Elasticsearch connection from its `ElasticsearchServerSettings`. What is left here belongs to this
source alone: which index it reads and the site it scrapes.
"""

from diffusion_core.settings import ElasticsearchServerSettings


class Settings(ElasticsearchServerSettings):
    """The insee.fr brick's settings.

    `ES_HOST` is required: every search tool here answers from the INSEE Elasticsearch indices.
    """

    # What this source reads from Elasticsearch ------------------------------------------------------------------------
    es_index_publications: str = "produit"

    # insee.fr, the website -------------------------------------------------------------------------------------------
    insee_base_url: str = "https://www.insee.fr"
    insee_request_timeout_seconds: int = 30
    insee_connect_timeout_seconds: int = 10
    # A rendered publication is truncated past this many characters, so one document cannot
    # fill the calling model's context. Tune it to the context budget of the client in use.
    insee_document_max_markdown_chars: int = 30_000


def load_settings() -> Settings:
    return Settings()
