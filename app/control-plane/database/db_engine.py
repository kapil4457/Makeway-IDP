"""
db_engine.py

Database engine and session management for the Makeway control plane.
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlmodel import create_engine, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/makeway",
)

# pool_pre_ping avoids stale connections after DB restarts or idle timeouts.
# pool_size/max_overflow tuned for a small control plane; raise if request
# volume grows.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency. Yields a session, guarantees close on request end.

    Usage:
        @router.get("/apps/{app_id}")
        def get_app(app_id: str, db: Session = Depends(get_db)):
            ...
    """
    with Session(engine) as session:
        yield session


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context-manager version for non-FastAPI callers (Lambda handlers,
    Fargate task callbacks, scripts, workers).

    Usage:
        with get_db_context() as db:
            db.exec(select(Capability).where(...)).first()
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """
    Closes all pooled connections. Call on app shutdown (see lifespan
    handler in main.py) to release DB connections cleanly.
    """
    engine.dispose()