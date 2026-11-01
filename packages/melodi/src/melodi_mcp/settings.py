"""Every value the MELODI brick can be configured with.

The HTTP-server, rate-limit and logging fields come from the core's `ServerSettings`, the
Elasticsearch connection from its `ElasticsearchServerSettings`. What is left here belongs to this
source alone: the two indices it reads and the observations API it calls.
"""

from diffusion_core.settings import ElasticsearchServerSettings


class Settings(ElasticsearchServerSettings):
    """The MELODI brick's settings.

    `ES_HOST` is required: the catalogue and the modality search answer from the INSEE
    Elasticsearch indices.
    """

    # What this source reads from Elasticsearch ------------------------------------------------------------------------
    es_index_melodi_datasets: str = "melodi_datasets"
    es_index_melodi_columns: str = "melodi_columns"

    # The MELODI REST API ----------------------------------------------------------------------------------------------
    melodi_data_base_url: str = "https://api.insee.fr/melodi/data"
    melodi_request_timeout_seconds: int = 30
    melodi_connect_timeout_seconds: int = 10


def load_settings() -> Settings:
    return Settings()
