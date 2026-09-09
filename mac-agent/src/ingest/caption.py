"""Caption providers and the parity harness.

Authority doctrine (packet §5 + repair R1/R2):
- The current stable provider (osxphotos description, as used by the production
  extraction path) remains the caption authority.
- ``caption_raw`` for the NEW backbone authority is the EXACT caption
  representation obtained from the provider BEFORE any application-level
  whitespace normalization. Dive Analyzer adds NO silent trim before the
  revision authority.
- The legacy production payload path (extractor.py) separately applies
  ``caption.strip()`` (see ``legacy_caption_transform`` below). That transform
  is legacy-derived behavior, retained exclusively in the legacy path, and is
  never applied to ``CaptionRevision.caption_raw``.
- The Photos-DB direct-SQLite reader is a SHADOW ONLY provenance cross-check.
  It is NOT PhotoKit: real PhotoKit caption shadow status is
  ``NOT_IMPLEMENTED_CURRENT_RUNTIME`` (see ``PHOTOKIT_CAPTION_SHADOW_STATUS``).
  The shadow never blocks ingestion and is never authoritative.

Caption SHA-256 is computed over the UTF-8 bytes of the exact persisted
representation with no normalization before hashing.
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

CAPTION_HASH_ENCODING = "utf-8"
PHOTOKIT_CAPTION_SHADOW_STATUS = "NOT_IMPLEMENTED_CURRENT_RUNTIME"
LEGACY_STRIP_BOUNDARY = "legacy extractor .strip() (extractor.py) — legacy path only"


def legacy_caption_transform(provider_caption: str) -> str:
    """The historical legacy-path transform (extractor.py:125).

    Retained ONLY for legacy payload construction and documentation. The new
    backbone revision authority must never call this on the value it persists.
    """
    return provider_caption.strip()


def caption_sha256(persisted_raw: str) -> str:
    """SHA-256 over the exact persisted representation (UTF-8), no normalization."""
    return hashlib.sha256(persisted_raw.encode(CAPTION_HASH_ENCODING)).hexdigest()


@dataclass(frozen=True)
class CaptionResult:
    provider: str
    available: bool
    raw: str | None
    sha256: str | None
    error: str | None = None
    provider_kind: str = ""
    provider_version: str = ""

    @property
    def effectively_empty(self) -> bool:
        """Derived gate flag (NOT a persisted transformation): True when the
        provider returned nothing usable. Consulted for ingest gating only;
        ``raw`` is never mutated because of it.
        """
        return self.raw is None or self.raw.strip() == ""

    @property
    def error_family(self) -> str | None:
        if self.error is None:
            return None
        return self.error.split(":", 1)[0]


class CaptionProvider(Protocol):
    name: str
    provider_kind: str

    def get_caption(self, video_uuid: str) -> CaptionResult: ...


class CurrentStableCaptionProvider:
    """Wraps the production osxphotos description read path.

    Returns the EXACT provider string (``photo.description``) — no strip, no
    normalization. If osxphotos itself normalizes internally, that is the
    provider boundary (documented); Dive Analyzer adds nothing.
    """

    name = "osxphotos_description_stable"
    provider_kind = "osxphotos_description"

    def __init__(self, describe: Callable[[str], str | None]):
        self._describe = describe

    def get_caption(self, video_uuid: str) -> CaptionResult:
        try:
            raw = self._describe(video_uuid)
        except Exception as exc:
            return CaptionResult(
                self.name, False, None, None,
                f"stable_provider_error: {exc}",
                provider_kind=self.provider_kind,
            )
        if raw is None:
            return CaptionResult(
                self.name, False, None, None, "no_caption",
                provider_kind=self.provider_kind,
            )
        return CaptionResult(
            self.name, True, raw, caption_sha256(raw), None,
            provider_kind=self.provider_kind,
        )


class PhotosDbCaptionProviderShadow:
    """SHADOW ONLY: direct read-only Photos-library SQLite read.

    NOT PhotoKit (see ``PHOTOKIT_CAPTION_SHADOW_STATUS``). The caption column
    is located by runtime introspection (``PRAGMA table_info(ZASSET)``); any
    obstacle reports ``available=False`` with an error reason. Ingestion never
    depends on this provider.
    """

    name = "photos_db_sqlite_shadow"
    provider_kind = "photos_db_sqlite"

    def __init__(self, library_path: str | Path):
        self._library_path = Path(library_path) / "database" / "Photos.sqlite"

    def get_caption(self, video_uuid: str) -> CaptionResult:
        try:
            uri = f"file:{self._library_path}?mode=ro"
            con = sqlite3.connect(uri, uri=True, timeout=5.0)
            try:
                con.execute("PRAGMA query_only=ON")
                columns = [
                    row[1]
                    for row in con.execute("PRAGMA table_info(ZASSET)").fetchall()
                ]
                caption_col = next(
                    (c for c in columns if "caption" in c.lower()), None
                )
                if caption_col is None:
                    return CaptionResult(
                        self.name, False, None, None, "shadow_column_not_found",
                        provider_kind=self.provider_kind,
                    )
                row = con.execute(
                    f'SELECT "{caption_col}" FROM ZASSET WHERE ZUUID = ?',
                    (video_uuid,),
                ).fetchone()
            finally:
                con.close()
        except Exception as exc:
            return CaptionResult(
                self.name, False, None, None, f"shadow_unavailable: {exc}",
                provider_kind=self.provider_kind,
            )
        if row is None or row[0] is None:
            return CaptionResult(
                self.name, False, None, None, "shadow_no_row",
                provider_kind=self.provider_kind,
            )
        raw = str(row[0])
        return CaptionResult(
            self.name, True, raw, caption_sha256(raw), None,
            provider_kind=self.provider_kind,
        )


def compare_caption_providers(
    samples: list[tuple[str, CaptionResult, CaptionResult]],
) -> dict:
    """Provider-independent caption parity harness.

    Accepts (video_uuid, stable_result, shadow_result) samples; any provider
    pair can be compared (stable vs Photos-DB shadow vs a future real PhotoKit
    shadow) without conflating identities. Reports redacted evidence only —
    no raw caption text appears in the result: identity metadata, hashes,
    lengths, error families.
    """
    exact_equal = 0
    samples_out = []
    mismatches = []
    failures = {"stable": 0, "shadow": 0}

    def _describe(result: CaptionResult) -> dict:
        return {
            "provider": result.provider,
            "provider_kind": result.provider_kind,
            "provider_version": result.provider_version,
            "available": result.available,
            "caption_sha256": result.sha256,
            "caption_length": len(result.raw) if result.raw is not None else None,
            "error_family": result.error_family,
        }

    for video_uuid, stable, shadow in samples:
        if not stable.available:
            failures["stable"] += 1
        if not shadow.available:
            failures["shadow"] += 1
        equal = bool(
            stable.available
            and shadow.available
            and stable.sha256 == shadow.sha256
            and stable.raw == shadow.raw
        )
        if equal:
            exact_equal += 1
        else:
            mismatches.append({"video_uuid": video_uuid})
        samples_out.append(
            {
                "video_uuid": video_uuid,
                "exact_equal": equal,
                "stable": _describe(stable),
                "shadow": _describe(shadow),
            }
        )
    sample_count = len(samples)
    return {
        "sample_count": sample_count,
        "exact_equal_count": exact_equal,
        "exact_equal_rate": (exact_equal / sample_count) if sample_count else None,
        "samples": samples_out,
        "mismatches": mismatches,
        "provider_failures": failures,
    }
