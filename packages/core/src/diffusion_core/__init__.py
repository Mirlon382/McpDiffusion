"""The shared application layer every diffusion brick is built from.

The rule that keeps this package honest: it holds only what would otherwise be *literally
identical* in two or more bricks. Anything specific to one data source stays in that source.
It imports nothing from any source package, and neither do its modules.

The error vocabulary (`AppToolError`, `ErrorCode`) and the server settings base
(`ServerSettings`) are re-exported here so callers name the concern rather than the file.
The Elasticsearch module is deliberately absent: it lives behind the `elasticsearch`
extra and must only be imported by a brick that installs it.
"""

from .app import McpApplication, create_server
from .errors import AppToolError, ErrorCode
from .settings import ServerSettings

__all__ = [
    "AppToolError",
    "ErrorCode",
    "McpApplication",
    "ServerSettings",
    "create_server",
]
