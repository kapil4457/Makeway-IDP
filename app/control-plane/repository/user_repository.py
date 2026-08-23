from sqlmodel import Session, select

from database.models.user import User
class UserRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_id(self, user_id: str) -> User | None:
        statement = select(User).where(
            User.userId == user_id
        )

        return self.session.exec(statement).first()

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(
            User.email == email
        )

        return self.session.exec(statement).first()

    def create(self, user:  User ) -> User:
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)

        return user