"""P9 §29 B2 inventory reconciliation tests (read-only logic, offline).

- verified PROD DB keys must all exist in the bucket (missing = drift)
- bucket keys must be content-addressed (malformed reported)
- orphans are REPORTED ONLY (the report never authorizes deletion)
- the module must not call the store's delete method (static + runtime)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ingest.b2_inventory import (
    InventoryReport,
    fetch_db_verified_prod_keys,
    list_bucket,
    reconcile,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_ORPHAN = "c" * 64

KEY_A = f"blobs/sha256/{SHA_A[:2]}/{SHA_A}.mov"
KEY_B = f"blobs/sha256/{SHA_B[:2]}/{SHA_B}.mov"
KEY_ORPHAN = f"blobs/sha256/{SHA_ORPHAN[:2]}/{SHA_ORPHAN}.mov"
KEY_MALFORMED = "blobs/sha256/zz/not-a-sha.mov"


def test_reconcile_clean_inventory():
    objects = [{"key": KEY_A, "size": 100}, {"key": KEY_B, "size": 200}]
    report = reconcile(objects, {KEY_A, KEY_B})
    assert report.object_count == 2
    assert report.total_bytes == 300
    assert report.malformed_keys == []
    assert report.missing_verified_keys == []
    assert report.orphans == []


def test_reconcile_missing_and_orphans_and_malformed():
    objects = [{"key": KEY_A, "size": 100}, {"key": KEY_ORPHAN, "size": 1},
               {"key": "blobs/sha256/zz/not-a-sha.mov", "size": 1}]
    report = reconcile(objects, {KEY_A, KEY_B})
    assert KEY_B in report.missing_verified_keys
    assert KEY_ORPHAN in report.orphans
    assert report.malformed_keys == ["blobs/sha256/zz/not-a-sha.mov"]
    # the report is informational: orphans are NEVER actions
    dumped = report.as_dict()
    assert dumped["orphans_note"].startswith("REPORTED ONLY")


def test_fetch_db_verified_prod_keys_filters_unverified_and_dev():
    items = [
        {"verified_prod": True, "prod_object_key": KEY_A},
        {"verified_prod": False, "prod_object_key": KEY_ORPHAN},
        {"verified_prod": True, "prod_object_key": None},
        {"verified_prod": True, "dev_object_key": KEY_B},
    ]
    assert fetch_db_verified_prod_keys(items) == {KEY_A}


def test_list_bucket_paginates(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.calls = 0

        def list_objects_v2(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"Contents": [{"Key": KEY_A, "Size": 1}],
                        "IsTruncated": True, "NextContinuationToken": "t1"}
            return {"Contents": [{"Key": KEY_B, "Size": 2}], "IsTruncated": False}

    class FakeStore:
        def __init__(self):
            self._client = FakeClient()
            from types import SimpleNamespace
            self.config = SimpleNamespace(bucket="fake-bucket")

    store = FakeStore()
    objects = list_bucket(store)
    assert [o["key"] for o in objects] == [KEY_A, KEY_B]
    assert store._client.calls == 2


def test_module_never_calls_delete():
    source = Path(__file__).resolve().parents[1] / "src" / "ingest" / "b2_inventory.py"
    text = source.read_text()
    for forbidden in ("delete_object", "delete_objects", ".delete(", "hide_object"):
        assert forbidden not in text, f"forbidden primitive {forbidden!r}"
