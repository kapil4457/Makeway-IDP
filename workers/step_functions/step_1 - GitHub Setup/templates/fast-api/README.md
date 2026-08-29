# __SERVICE_NAME__ — FastAPI service scaffolded by Makeway

## Layout

- `main.py` — FastAPI app, `/` and `/health`
- `setup.sh` — golden-path setup (venv + deps + smoke check)
- `Dockerfile` — python:3.12-slim, uvicorn on :8000

## Run locally

```bash
./setup.sh
. .venv/bin/activate
uvicorn main:app --reload
```

## Health

`GET /health` → `{"status": "healthy"}`