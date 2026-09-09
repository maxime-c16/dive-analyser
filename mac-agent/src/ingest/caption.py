"""Caption providers and the parity harness.

Authority doctrine (packet §5):
- The current stable provider (osxphotos description, as used by the production
  extraction path) remains the caption authority.
- The PhotoKit/direct-DB shadow is SHADOW ONLY: it never blocks ingestion and is
  never authoritative.

Raw-capture boundary documented (fresh evidence, extractor.py:125 and
photos_reader.py:126): the production extraction path persists
``caption.strip()`` — leading/trailing whitespace is stripped at the agent
boundary. This provider reproduces exactly that persisted representation and
applies NO further transformation: no Unicode normalization, no whitespace
collapse, no punctuation rewriting, no newline convention change. Caption
SHA-256 is computed over the UTF-8 bytes of the exact persisted representation.
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

CAPTION_HASH_ENCODING = "utf-8"
STRIP_BOUNDARY = "strip"


@dataclass(frozen=True)
class CaptionResult:
    provider: str
    available: bool
    raw: str | None
    sha256: str | None
    error: str | None = None


def caption_sha256(persisted_raw: str) -> str:
    return hashlib.sha256(persisted_raw.encode(CAPTION_HASH_ENCODING)).hexdigest()


class CaptionProvider(Protocol):
    name: str

    def get_caption(self, video_uuid: str) -> CaptionResult: ...


class CurrentStableCaptionProvider:
    """Wraps the production osxphotos description read path."""

    name = "osxphotos_description_stable"

    def __init__(self, describe: Callable[[str], str | None]):
        self._describe = describe

    def get_caption(self, video_uuid: str) -> CaptionResult:
        try:
            raw = self._describe(video_uuid)
        except Exception as exc:
            return CaptionResult(self.name, False, None, None, f"stable_provider_error: {exc}")
        if raw is None:
            return CaptionResult(self.name, False, None, None, "no_caption")
        persisted = raw.strip()
        if persisted == "":
            return CaptionResult(self.name, False, persisted, None, "empty_caption")
        return CaptionResult(self.name, True, persisted, caption_sha256(persisted))


class PhotoKitCaptionProviderShadow:
    """SHADOW ONLY. Independent read-only direct-SQLite read of the Photos DB.

    Reports available=False with an error reason whenever the caption column
    cannot be located safely on the current runtime; ingestion never depends on
    this provider.
    """

    name = "photokit_direct_sqlite_shadow"

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
                        self.name, False, None, None, "shadow_column_not_found"
                    )
                row = con.execute(
                    f'SELECT "{caption_col}" FROM ZASSET WHERE ZUUID = ?',
                    (video_uuid,),
                ).fetchone()
            finally:
                con.close()
        except Exception as exc:
            return CaptionResult(self.name, False, None, None, f"shadow_unavailable: {exc}")
        if row is None or row[0] is None:
            return CaptionResult(self.name, False, None, None, "shadow_no_row")
        raw = str(row[0]).strip()
        if raw == "":
            return CaptionResult(self.name, False, raw, None, "shadow_empty_caption")
        return CaptionResult(self.name, True, raw, caption_sha256(raw))


def compare_caption_providers(
    samples: list[tuple[str, CaptionResult, CaptionResult]],
) -> dict:
    """Caption parity harness. Reports redacted evidence only: no raw caption
    text appears in the result — only uuid, hashes, lengths, and error families.
    """
    exact_equal = 0
    mismatches = []
    provider_failures = {"stable": 0, "shadow": 0}
    for video_uuid, stable, shadow in samples:
        if not stable.available:
            provider_failures["stable"] += 1
        if not shadow.available:
            provider_failures["shadow"] += 1
        if stable.available and shadow.available:
            if stable.sha256 == shadow.sha256 and stable.raw == shadow.raw:
                exact_equal += 1
            else:
                mismatches.append(
                    {
                        "video_uuid": video_uuid,
                        "stable_sha256": stable.sha256,
                        "shadow_sha256": shadow.sha256,
                        "stable_len": len(stable.raw or ""),
                        "shadow_len": len(shadow.raw or ""),
                    }
                )
    sample_count = len(samples)
    return {
        "sample_count": sample_count,
        "exact_equal_count": exact_equal,
        "exact_equal_rate": (exact_equal / sample_count) if sample_count else None,
        "mismatches": mismatches,
        "provider_failures": provider_failures,
    }
