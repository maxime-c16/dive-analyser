"""Typed domain errors for the object-store backbone."""


class ObjectStoreError(Exception):
    """Base class for object-store failures."""


class ConfigValidationError(ObjectStoreError):
    """Configuration rejected by the B2 configuration firewall."""


class ObjectStoreUnavailable(ObjectStoreError):
    """Transient/unavailable backend condition (retryable)."""


class ObjectStoreVerificationError(ObjectStoreError):
    """Roundtrip verification failed; fail closed."""


class ObjectStoreNotFound(ObjectStoreError):
    """Object does not exist."""
