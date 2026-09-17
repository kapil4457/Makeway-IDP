from pydantic import BaseModel, Field, HttpUrl


class ClusterUpdateRequest(BaseModel):
    """Partial update for an existing cluster (``PUT /cluster/{cluster_id}``).

    Every field is optional; omitted fields stay unchanged. ``environment``
    is deliberately absent — it is the routing key for app creation
    (``get_by_env``) and register already rejects moving it, so updates
    cannot move it either. Token/CA follow register's rule: ``None`` leaves
    the stored credential untouched, so a metadata-only update never wipes a
    secret. Clearing a credential is not supported by this endpoint —
    re-register or delete the cluster instead.
    """

    clusterName: str | None = Field(
        default=None,
        description="New cluster name. Uniqueness is enforced.",
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$",
        examples=["makeway-kube-prod"],
    )
    kubeApiEndpoint: HttpUrl | None = Field(
        default=None,
        description=(
            "New API endpoint the Step-2 worker talks to — e.g. pointing a "
            "tunnel-registered cluster at its replacement endpoint."
        ),
        examples=["https://10.0.4.17:6443"],
    )
    kubeToken: str | None = Field(
        default=None,
        description=(
            "Replacement worker token. Omitted (None) keeps the stored "
            "value; there is no way to clear it here."
        ),
    )
    kubeCaCert: str | None = Field(
        default=None,
        description=(
            "Replacement base64 CA bundle. Omitted (None) keeps the stored "
            "value; there is no way to clear it here."
        ),
    )
