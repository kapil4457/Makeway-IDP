from fastapi import Depends
from sqlmodel import Session

from dependencies.database import get_database_session
from repository.cluster_repository import ClusterRepository
from service.cluster_service import ClusterService


def get_cluster_repository(session: Session = Depends(get_database_session)) -> ClusterRepository:
    return ClusterRepository(session)


def get_cluster_service(repository: ClusterRepository = Depends(get_cluster_repository),) -> ClusterService:
    return ClusterService(repository)