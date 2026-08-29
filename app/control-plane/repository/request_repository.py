from sqlmodel import Session, select

from database.models.request import Request


class RequestRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Request | None:

        statement = select(Request).where(
            Request.idempotencyKey == idempotency_key
        )

        return self.session.exec(statement).first()

    def get_by_id(
        self,
        request_id: int,
    ) -> Request | None:

        statement = select(Request).where(
            Request.requestId == request_id
        )

        return self.session.exec(statement).first()

    def create(
        self,
        request: Request,
    ) -> Request:

        self.session.add(request)
        self.session.flush()
        self.session.refresh(request)

        return request