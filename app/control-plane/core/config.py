"""Platform-level configuration constants.

Values that are constant across every app and environment live here rather
than in per-row database columns, so the schema stores only what actually
varies per app.
"""

import os

GITOPS_REPO_URL = os.environ.get(
    "GITOPS_REPO_URL",
    "https://github.com/kapil4457/Makeway-IDP",
)