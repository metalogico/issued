"""Web reader for Issued comic library.

Serves /reader for browsing the library and reading comics in the browser.
"""

from .router import router

__all__ = ["router"]
