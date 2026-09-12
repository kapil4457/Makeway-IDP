from sqlmodel import Session, select

from database.models.app import App


class AppRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_name(self, app_name: str) -> App | None:
        apps = select(App).where(
            App.appName == app_name
        )

        return self.session.exec(apps).first()

    def get_by_id(self, app_id: int) -> App | None:
        apps = select(App).where(
            App.appId == app_id
        )

        return self.session.exec(apps).first()

    def list_by_team_ids(self, team_ids: list[int]) -> list[App]:
        """
        Apps owned by any of the given teams, most recently modified first.

        Read-only. An empty ``team_ids`` short-circuits to ``[]`` so callers
        without team membership never trigger a broad scan.
        """
        if not team_ids:
            return []

        statement = (
            select(App)
            .where(App.teamId.in_(team_ids))
            .order_by(App.modifiedAt.desc())
        )

        return list(self.session.exec(statement).all())

    def create(self, app: App) -> App:
        """
        Persist a new app within the calling unit of work.

        Flushed (not committed) so the auto-generated ``appId`` is available
        to related rows (services, capabilities, request) before the caller
        performs the single ``commit`` that makes the whole registration
        atomic.
        """
        self.session.add(app)
        self.session.flush()

        return app