from sqlmodel import Session, select

from database.models.job import Job


class JobRepository:

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        job: Job,
    ) -> Job:
        """
        Persist a new job within the calling unit of work.
        Flushed, not committed — the caller owns the eventual ``commit``.
        """
        self.session.add(job)
        self.session.flush()

        return job

    def get_by_id(
        self,
        job_id: int,
    ) -> Job | None:

        statement = select(Job).where(
            Job.jobId == job_id
        )

        return self.session.exec(statement).first()

    def get_by_request_id(
        self,
        request_id: int,
    ) -> Job | None:
        """Get the most recent job associated with a request."""

        statement = (
            select(Job)
            .where(Job.requestId == request_id)
            .order_by(Job.jobId.desc())
        )

        return self.session.exec(statement).first()