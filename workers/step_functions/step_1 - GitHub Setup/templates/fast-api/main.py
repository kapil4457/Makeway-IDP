"""Golden-path FastAPI service scaffold, rendered by the Makeway Step-1 worker.

The __SERVICE_NAME__ token is substituted at render time with the service's
base name before this file is pushed to the app's services repository.
"""

import os

from fastapi import FastAPI

SERVICE_NAME = os.getenv("SERVICE_NAME", "__SERVICE_NAME__")

app = FastAPI(
    title=SERVICE_NAME,
    version="0.1.0",
)


@app.get("/")
def root() -> dict:
    return {"service": SERVICE_NAME, "status": "ok"}


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}