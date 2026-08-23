from enum import Enum

class JobStep(str, Enum):
    """Step in the job execution process."""

    CREATE_PROJECT = "create_project"
    PROVISION_INFRA = "provision_infra"
    ARGOCD_SETUP = "argocd_setup"