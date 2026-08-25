from sqlmodel import Session, select

from database.models.service import Service


class ServiceRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_name(self, svc_name: str) -> Service | None:
        """
        Get a service by its name.

        A service name is globally unique because it is derived from the
        service name plus the environment. See how `svcName` is set during
        app creation (e.g. ``orders-api-dev``).
        """
        statement = select(Service).where(
            Service.svcName == svc_name
        )

        return self.session.exec(statement).first()

    def get_by_app(
        self,
        app_id: int,
        cluster_id: int | None = None,
    ) -> list[Service]:
        """Get all services belonging to an application, optionally scoped to a cluster."""

        statement = select(Service).where(
            Service.appId == app_id,
        )

        if cluster_id is not None:
            statement = statement.where(Service.clusterId == cluster_id)

        return self.session.exec(statement).all()

    def create(self, service: Service) -> Service:
        self.session.add(service)
        self.session.flush()
        self.session.refresh(service)

        return service