from sqlmodel import Session, select

from database.models.capability import Capability


class CapabilityRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, capability_id: int) -> Capability | None:
        statement = select(Capability).where(
            Capability.capabilityId == capability_id
        )

        return self.session.exec(statement).first()

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