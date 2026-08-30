from fastapi import Depends
from sqlmodel import Session

from dependencies.database import get_database_session

from repository.request_repository import RequestRepository
from repository.app_repository import AppRepository
from repository.team_repository import TeamMemberRepository
from repository.cluster_repository import ClusterRepository
from repository.service_repository import ServiceRepository
from repository.capability_repository import CapabilityRepository
from repository.infra_requirement_repository import InfraRequirementRepository
from repository.capability_access_repository import CapabilityAccessRepository
from repository.job_repository import JobRepository
from repository.deployment_setup_repository import DeploymentSetupRepository

from service.app_creation_queue import AppCreationQueue
from service.app_creation_service import AppCreationService
from service.app_status_service import AppStatusService


def get_app_creation_service(
    session: Session = Depends(get_database_session),
) -> AppCreationService:

    request_repository = RequestRepository(session)
    app_repository = AppRepository(session)
    team_member_repository = TeamMemberRepository(session)
    cluster_repository = ClusterRepository(session)
    service_repository = ServiceRepository(session)
    capability_repository = CapabilityRepository(session)
    infra_requirement_repository = InfraRequirementRepository(session)
    capability_access_repository = CapabilityAccessRepository(session)
    job_repository = JobRepository(session)
    queue = AppCreationQueue()

    return AppCreationService(
        session=session,
        queue=queue,
        teamMemberRepository=team_member_repository,
        appRepository=app_repository,
        clusterRepository=cluster_repository,
        serviceRepository=service_repository,
        capabilityRepository=capability_repository,
        infraRequirementRepository=infra_requirement_repository,
        capabilityAccessRepository=capability_access_repository,
        requestRepository=request_repository,
        jobRepository=job_repository,
    )


def get_app_status_service(
    session: Session = Depends(get_database_session),
) -> AppStatusService:

    app_repository = AppRepository(session)
    team_member_repository = TeamMemberRepository(session)
    cluster_repository = ClusterRepository(session)
    service_repository = ServiceRepository(session)
    capability_repository = CapabilityRepository(session)
    capability_access_repository = CapabilityAccessRepository(session)
    infra_requirement_repository = InfraRequirementRepository(session)
    deployment_setup_repository = DeploymentSetupRepository(session)
    request_repository = RequestRepository(session)
    job_repository = JobRepository(session)

    return AppStatusService(
        session=session,
        appRepository=app_repository,
        teamMemberRepository=team_member_repository,
        clusterRepository=cluster_repository,
        serviceRepository=service_repository,
        capabilityRepository=capability_repository,
        capabilityAccessRepository=capability_access_repository,
        infraRequirementRepository=infra_requirement_repository,
        deploymentSetupRepository=deployment_setup_repository,
        requestRepository=request_repository,
        jobRepository=job_repository,
    )


def get_app_repository(
    session: Session = Depends(get_database_session),
) -> AppRepository:
    return AppRepository(session)