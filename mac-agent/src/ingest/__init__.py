"""Object-store media ingest backbone (additive, feature-flagged).

See docs/architecture/MEDIA_BACKBONE_TARGET_V1.md and
docs/architecture/MEDIA_INGEST_STATE_MACHINE_V1.md.
"""

from .content_addr import (
    SHA256_RE,
    object_key_for_sha,
    sha256_bytes,
    sha256_file,
    validate_sha256,
)
from .errors import (
    ConfigValidationError,
    ObjectStoreError,
    ObjectStoreUnavailable,
    ObjectStoreVerificationError,
)
from .objectstore.base import ObjectHead, ObjectStore, PutResult
from .objectstore.fake import FakeObjectStore
from .objectstore.b2 import B2Config, BackblazeB2Store
from .states import IngestState
from .state_store import IngestStateStore
from .caption import (
    CaptionResult,
    CaptionProvider,
    CurrentStableCaptionProvider,
    PhotoKitCaptionProviderShadow,
    caption_sha256,
    compare_caption_providers,
)
from .coordinator import ObjectStoreIngestCoordinator

__all__ = [
    "SHA256_RE",
    "object_key_for_sha",
    "sha256_bytes",
    "sha256_file",
    "validate_sha256",
    "ConfigValidationError",
    "ObjectStoreError",
    "ObjectStoreUnavailable",
    "ObjectStoreVerificationError",
    "ObjectHead",
    "ObjectStore",
    "PutResult",
    "FakeObjectStore",
    "B2Config",
    "BackblazeB2Store",
    "IngestState",
    "IngestStateStore",
    "CaptionResult",
    "CaptionProvider",
    "CurrentStableCaptionProvider",
    "PhotoKitCaptionProviderShadow",
    "caption_sha256",
    "compare_caption_providers",
    "ObjectStoreIngestCoordinator",
]
