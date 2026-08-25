from sqlmodel import Session, select

from database.models.capability_access import CapabilityAccess


class CapabilityAccessRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_capability(
        self,
        capability_id: int,
    ) -> list[CapabilityAccess]:
        statement = select(CapabilityAccess).where(
            CapabilityAccess.capabilityId == capability_id
        )

        return self.session.exec(statement).all()

    def create(
        self,
        capability_access: CapabilityAccess,
    ) -> CapabilityAccess:
        """
        Persist a new capability/service access binding within the calling
        unit of work. Flushed, not committed — the caller owns the eventual
        ``commit``.
        """
        self.session.add(capability_access)
        self.session.flush()

        return capability_access