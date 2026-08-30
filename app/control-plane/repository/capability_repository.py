from sqlmodel import Session, select

from database.models.capability import Capability
from database.models.capability_access import CapabilityAccess
from database.models.service import Service


class CapabilityRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, capability_id: int) -> Capability | None:
        statement = select(Capability).where(
            Capability.capabilityId == capability_id
        )

        return self.session.exec(statement).first()

    def get_by_app(self, app_id: int) -> list[Capability]:
        """All capabilities belonging to an app (via CapabilityAccess -> Service).

        A capability is environment-scoped at creation: one Capability row per
        ``env_config`` entry, linked to that environment's services through
        CapabilityAccess. The app itself has no FK from Capability, so this
        walks the access edges the app-creation service built.
        """
        statement = (
            select(Capability)
            .join(CapabilityAccess, CapabilityAccess.capabilityId == Capability.capabilityId)
            .join(Service, Service.svcId == CapabilityAccess.serviceId)
            .where(Service.appId == app_id)
            .distinct()
        )

        return self.session.exec(statement).all()

    def create(self, capability: Capability) -> Capability:
        """
        Persist a new capability.

        The row is flushed (not committed) so the auto-generated
        ``capabilityId`` is available for related rows (e.g. an infra
        requirement or an access binding) within the same unit of work.
        The caller owns the eventual ``commit``.
        """
        self.session.add(capability)
        self.session.flush()

        return capability