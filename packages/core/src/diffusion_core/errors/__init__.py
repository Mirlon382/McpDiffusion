"""The error contract: the single type tools and services raise, shared by every brick.

Re-exported here so callers name the concern rather than the file: `from diffusion_core.errors
import AppToolError`. The per-backend translators live in their own modules.
"""

from .error import AppToolError, ErrorCode

__all__ = [
    "AppToolError",
    "ErrorCode",
]
