from fastapi import Depends
from sqlmodel import Session

from dependencies.database import get_database_session
from repository.cluster_repository import ClusterRepository
from repository.service_repository import ServiceRepository
from service.cluster_service import ClusterService


def get_cluster_repository(session: Session = Depends(get_database_session)) -> ClusterRepository:
    return ClusterRepository(session)


def get_cluster_service(
    session: Session = Depends(get_database_session),
    repository: ClusterRepository = Depends(get_cluster_repository),
) -> ClusterService:
    return ClusterService(repository, ServiceRepository(session))