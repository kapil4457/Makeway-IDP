from enum import Enum


class CapabilityType(str, Enum):
    """Single source of truth for capability type discriminators.

    Values match the `type` field on all config DTOs (`DatabaseConfig`,
    `StorageConfig`, `MessagingConfig`) and the `Tag` annotations in
    `CapabilityConfig` union. This is the canonical discriminator used throughout
    the app-creation flow and persistence layer.
    """

    REL_DATABASE = "rel_database"
    STORAGE = "storage"
    MESSAGING = "messaging"