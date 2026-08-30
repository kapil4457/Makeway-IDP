from datetime import datetime

from sqlmodel import Session, select

from database.models.deployment_setup import DeploymentSetup


class DeploymentSetupRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_service_id(self, svc_id: int) -> DeploymentSetup | None:
        """Most recent deployment setup for a service (a service can have
        several over its life; the latest drives current rollout state)."""

        statement = (
            select(DeploymentSetup)
            .where(DeploymentSetup.serviceId == svc_id)
            .order_by(DeploymentSetup.deploymentSetupId.desc())
        )

        return self.session.exec(statement).first()

    def upsert(self, svc_id: int, values: dict) -> DeploymentSetup:
        """Create-or-update the latest deployment setup for a service.

        Values use the model's column names (``status``, ``argocdAppName``,
        ``lastSyncedAt``, ``errorMessage``). Keys that arrive as ``None``
        clear the column (an error is cleared once the next sync succeeds);
        keys absent from ``values`` are left untouched so a partial report
        never wipes fields the reporter did not include. This one upsert is
        the reporter's idempotency seam — retries reconcile, never duplicate.
        """
        existing = self.get_by_service_id(svc_id)
        if existing is None:
            row = DeploymentSetup(serviceId=svc_id, **values)
            self.session.add(row)
            self.session.flush()
            return row

        for column, value in values.items():
            setattr(existing, column, value)
        self.session.add(existing)
        self.session.flush()
        return existing

    def create(self, deployment_setup: DeploymentSetup) -> DeploymentSetup:
        self.session.add(deployment_setup)
        self.session.flush()

        return deployment_setup