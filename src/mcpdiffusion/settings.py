"""The aggregate's process settings: its HTTP server and shared middleware only."""

from diffusion_core.settings import ServerSettings


class Settings(ServerSettings):
    """Configuration for the aggregate process; source settings belong to their bricks."""


def load_settings() -> Settings:
    return Settings()
