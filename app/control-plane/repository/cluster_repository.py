from sqlmodel import Session, select

from database.models.cluster import Cluster


class ClusterRepository:

    def __init__(self, session: Session):
        self.session = session

    def get_by_name(self, cluster_name: str) -> Cluster | None:
        clusters = select(Cluster).where(
            Cluster.clusterName == cluster_name
        )

        return self.session.exec(clusters).first()

    def get_by_env(self,env_name:str)->Cluster | None:
        clusters = select(Cluster).where(
            Cluster.environment == env_name
        )
        return self.session.exec(clusters).first()



    def create(self, cluster: Cluster) -> Cluster:
        self.session.add(cluster)
        self.session.commit()
        self.session.refresh(cluster)

        return cluster