"""Persistent resumable ingest state (JSON file, atomic writes).

Same durability convention as the agent's existing sync_state.json:
tmp file + os.replace. The state file is the operational authority for
restart/resume; it must be sufficient to answer after a crash:
what completed, what is safe to retry, what must not be repeated, what remote
object should already exist, whether DB commit occurred, whether local temp
bytes can be deleted.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .states import IngestState

MAX_HISTORY_EVENTS = 200


class IngestStateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._doc: dict[str, Any] | None = None

    def load(self, video_uuid: str) -> dict[str, Any]:
        doc: dict[str, Any] | None = None
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
        if not doc or doc.get("video_uuid") != video_uuid:
            doc = {
                "video_uuid": video_uuid,
                "state": IngestState.DISCOVERED.value,
                "created_at": _now(),
                "updated_at": _now(),
                "caption": None,
                "media": None,
                "remote": {"verified": False, "attempts": 0},
                "db_commit": {"committed": False},
                "attempts": 0,
                "last_error": None,
                "history": [],
            }
            self._persist(doc)
        self._doc = doc
        return doc

    @property
    def doc(self) -> dict[str, Any]:
        if self._doc is None:
            raise RuntimeError("load() must be called first")
        return self._doc

    @property
    def state(self) -> IngestState:
        return IngestState(self.doc["state"])

    def transition(self, next_state: IngestState, **fields: Any) -> None:
        doc = self.doc
        doc["state"] = next_state.value
        doc["updated_at"] = _now()
        for key, value in fields.items():
            doc[key] = value
        doc.setdefault("history", []).append(
            {"state": next_state.value, "at": _now()}
        )
        if len(doc["history"]) > MAX_HISTORY_EVENTS:
            doc["history"] = doc["history"][-MAX_HISTORY_EVENTS:]
        self._persist(doc)

    def record_retryable_error(self, error_family: str, detail: str) -> None:
        doc = self.doc
        doc["attempts"] = int(doc.get("attempts", 0)) + 1
        doc["last_error"] = {
            "family": error_family,
            "detail": detail[:500],
            "at": _now(),
        }
        doc["updated_at"] = _now()
        self._persist(doc)

    def quarantine(self, error_family: str, detail: str) -> None:
        self.transition(
            IngestState.QUARANTINED,
            last_error={"family": error_family, "detail": detail[:500], "at": _now()},
        )

    def persist(self) -> None:
        self._persist(self.doc)

    def reconcile_to_media_requested(self, reason: str) -> None:
        doc = self.doc
        doc["media"] = None
        doc["state"] = IngestState.MEDIA_REQUESTED.value
        doc["updated_at"] = _now()
        doc.setdefault("history", []).append(
            {"state": IngestState.MEDIA_REQUESTED.value, "at": _now(), "reconcile": reason}
        )
        if len(doc["history"]) > MAX_HISTORY_EVENTS:
            doc["history"] = doc["history"][-MAX_HISTORY_EVENTS:]
        self._persist(doc)

    def _persist(self, doc: dict[str, Any]) -> None:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".ingest_state.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
