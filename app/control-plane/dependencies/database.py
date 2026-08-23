from fastapi import Depends
from sqlmodel import Session

from database.db_engine import get_session


def get_database_session(session: Session = Depends(get_session)) -> Session:
    return session