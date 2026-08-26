"""Shared configuration for operational scripts."""

import os

# Default password for users created from the CLI. Over-ridable via env so
# the value is never hard-coded across scripts. Suitable for bootstrap /
# local development only — production must always pass an explicit password.
DEFAULT_PASSWORD = os.getenv("FORGE_DEFAULT_PASSWORD", "changeme123")