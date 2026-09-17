from sqlmodel import Session, select

from database.models.service import Service


class ServiceRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, svc_id: int) -> Service | None:
        statement = select(Service).where(
            Service.svcId == svc_id
        )

        return self.session.exec(statement).first()

    def get_by_name(self, svc_name: str, app_id: int | None = None) -> Service | None:
        """
        Get one of an application's services by its full row name
        (``{base}-{env}``, e.g. ``orders-api-qa``).

        svcName is unique only WITHIN an app: two apps each get their own
        ``orders-api-qa`` row, so a lookup without ``app_id`` can return
        another application's row. Callers that resolve a name on behalf of
        an app must pass ``app_id``.
        """
        statement = select(Service).where(
            Service.svcName == svc_name
        )

        if app_id is not None:
            statement = statement.where(Service.appId == app_id)

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

    def get_by_cluster(self, cluster_id: int) -> list[Service]:
        """All service rows deployed to a cluster, across every app."""
        statement = select(Service).where(
            Service.clusterId == cluster_id,
        )

        return self.session.exec(statement).all()

    def create(self, service: Service) -> Service:
        self.session.add(service)
        self.session.flush()
        self.session.refresh(service)

        return service

    def delete(self, service: Service) -> None:
        """
        Remove a service row within the calling unit of work. Flushed, not
        committed — the caller owns the eventual ``commit`` (and the FK
        ordering: access/deployment rows must go first).
        """
        self.session.delete(service)
        self.session.flush()