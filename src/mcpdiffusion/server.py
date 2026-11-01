"""Entrypoint: mount the three source servers into one aggregate MCP application."""

from importlib.metadata import version as package_version

from diffusion_core import create_server

from .assembly import BRICKS, aggregate_health_check, build_instructions, register_bricks
from .settings import load_settings

settings = load_settings()
application = create_server(
    name="INSEE-mcp-diffusion",
    version=package_version("mcpdiffusion"),
    instructions=build_instructions(BRICKS),
    lifespan=None,
    health_check=aggregate_health_check,
    register=register_bricks,
    settings=settings,
)
app = application.app
mcp = application.mcp

if __name__ == "__main__":
    application.run()
