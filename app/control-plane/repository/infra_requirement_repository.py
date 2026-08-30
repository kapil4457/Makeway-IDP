from sqlmodel import Session, select

from database.models.infra_requirement import InfraRequirement


class InfraRequirementRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, infra_requirement_id: int) -> InfraRequirement | None:
        statement = select(InfraRequirement).where(
            InfraRequirement.infraRequirementId == infra_requirement_id
        )

        return self.session.exec(statement).first()

    def get_by_capability(self, capability_id: int) -> InfraRequirement | None:
        """The 1:1 InfraRequirement holding a capability's desired config.

        ``config`` (the serialized capability config) lives here, not on the
        Capability row — the provision-infra worker reads it to render a Claim.
        """
        statement = select(InfraRequirement).where(
            InfraRequirement.capabilityId == capability_id
        )

        return self.session.exec(statement).first()

    def create(self, infra_requirement: InfraRequirement) -> InfraRequirement:
        """
        Persist a new infra requirement within the calling unit of work.
        Flushed, not committed — the caller owns the eventual ``commit``.
        """
        self.session.add(infra_requirement)
        self.session.flush()

        return infra_requirement