from enum import Enum

class RequestType(str, Enum):
    """Type of a request in the Makeway platform."""

    CREATE_APP = "create_app"
    ADD_CAPABILITY = "add_capability"
    DELETE_CAPABILITY = "delete_capability"
    DELETE_APP = "delete_app"
    UPDATE_RESOURCE = "update_resource"
    UPDATE_APP = "update_app"