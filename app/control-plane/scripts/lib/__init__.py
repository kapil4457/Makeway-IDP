"""Shared utilities for Makeway operational scripts.

This package centralises the business logic used by the CLI scripts under
``scripts/`` so that each script stays a thin argument-parsing wrapper while
the DB access, audit fields and error handling live in one place.

Importing this package bootstraps the structured logger once; every script
and helper underneath ``lib`` therefore logs consistently without each
module needing to call ``setup_logging()`` itself.
"""

from core.logger import setup_logging

setup_logging()

__all__: list[str] = []