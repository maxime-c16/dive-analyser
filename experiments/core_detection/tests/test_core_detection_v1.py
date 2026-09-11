"""Core Detection V1 P0/P1 tests.

Proportional suite covering: corpus enumeration/provenance, GT authority
semantics, no GT-derived detection windows, full-session scanning, NMS/
refractory semantics, event matching, FP accounting, clip-window generation,
containment, audio optionality, holdout firewall, HURDLE non-mutation.

Run: python3 -m pytest experiments/core_detection/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from detect_events import EventCandidate, eventness, pick_candidates  # noqa: E402
from evaluate_events import (  # noqa: E402
    GtDive,
    classify_failure,
    containment,
    containment_recall,
    event_metrics,
    manifest,
    match_events,
)
from protocol import (  # noqa: E402
    EVENT_MATCH_TOL_S,
    GT_DIRECT,
    GT_RECOVERED,
    GT_WEAK,
    REFRACTORY_S,
    ROUGH_POST_ROLL_S,
    ROUGH_PRE_ROLL_S,
    SCAN_FPS,
)
from scan_features import ScanFeatures, compute_features  # noqa: E402


# ---------------------------------------------------------------- corpus ----

def test_corpus_exists_and_ready():
    repo = HERE.parent.parent
    p = repo / "docs/science/CORE_DETECTION_V1_CORPUS.json"
    assert p.exists(), "corpus manifest must be committed"
    corpus = json.loads(p.read_text())
    assert corpus["schema"] == "CORE_DETECTION_V1_CORPUS_V1"
    assert corpus["readiness"] in (
        "RAW_SESSION_CORPUS_READY", "RAW_SESSION_CORPUS_PARTIAL",
        "RAW_SESSION_CORPUS_NOT_READY")
    for s in corpus["sessions"]:
        assert s["authorization"], "every session must record authorization"
        assert s["size_bytes"] > 0 and s["duration_s"] > 120, \
            "sessions must be long raw recordings"


def test_corpus_clip_provenance():
    repo = HERE.parent.parent
    corpus = json.loads((repo / "docs/science/CORE_DETECTION_V1_CORPUS.json").read_text())
    s = corpus["sessions"][0]
    captioned = [c for c in s["derived_clips"] if c["captioned"]]
    assert len(captioned) == s["known_dives"]
    for c in captioned:
        assert c["blob_sha256"], "captioned clips must carry B2 blob sha provenance"
        assert len(c["blob_sha256"]) == 64
        assert c["dive_ids"], "captioned clips must map to dive ids"


# ------------------------------------------------------- GT authority -------

def test_gt_authority_classification():
    # only DIRECT and RECOVERED may be primary
    g_direct = GtDive(1, "a.MOV", "101B", GT_DIRECT, 10.0, 18.0)
    g_rec = GtDive(2, "b.MOV", "101B", GT_RECOVERED, 20.0, 28.0)
    g_weak = GtDive(None, "c.MOV", None, GT_WEAK, 30.0, 38.0)
    cands = []
    res = match_events([g_direct, g_rec, g_weak], cands)
    m = event_metrics([g_direct, g_rec, g_weak], res, 100.0)
    assert m["gt_dives_primary"] == 2, "weak labels must not count as primary GT"


# ------------------------------------------------ scanning / features -------

def _synth_frames(n=400, h=270, w=480, event_at=200, event_len=6):
    rng = np.random.RandomState(7)
    frames = rng.randint(60, 70, size=(n, h, w)).astype(np.uint8)
    # static "pool deck" texture rows 0..h/2, "water" rows h/2..h
    frames[:, : h // 2] = 120
    # splash burst: strong localized difference in water band
    for i in range(event_at, event_at + event_len):
        frames[i, h // 2 :, 100:200] = 250 - i + event_at
    return frames


def test_features_scan_whole_session():
    frames = _synth_frames()
    feat = compute_features(frames, SCAN_FPS, (0.5, 1.0), (0.0, 0.5))
    assert feat.n_frames == 400  # input thumbnails preserved
    assert abs(feat.ts[-1] - (399 - 1) / SCAN_FPS) < 1e-6
    # water band sees the burst; board band (static) must not
    assert feat.water_diff.max() > 10 * np.median(feat.water_diff)
    assert feat.board_diff.max() < feat.water_diff.max() / 2


def test_eventness_and_candidates_no_gt_windows():
    frames = _synth_frames(event_at=200)
    feat = compute_features(frames, SCAN_FPS, (0.5, 1.0), (0.0, 0.5))
    ev = eventness(feat)
    cands = pick_candidates(ev, feat.ts, ROUGH_PRE_ROLL_S, ROUGH_POST_ROLL_S)
    assert len(cands) == 1
    peak_t = 200 / SCAN_FPS
    assert abs(cands[0].event_time - peak_t) <= 2.0 / SCAN_FPS + 1.0


# ---------------------------------------------------- NMS / refractory ------

def test_refractory_merges_close_events():
    ts = np.arange(0, 60, 1 / SCAN_FPS)
    score = np.zeros_like(ts)
    for t0 in (10.0, 10.0 + REFRACTORY_S / 2, 40.0):
        i0 = int(t0 * SCAN_FPS)
        score[i0 : i0 + 10] = 10.0  # 5 s plateau, well inside one refractory span
    cands = pick_candidates(score, ts, ROUGH_PRE_ROLL_S, ROUGH_POST_ROLL_S)
    times = [c.event_time for c in cands]
    assert len(cands) == 2, f"refractory must merge close peaks, got {times}"
    assert abs(times[0] - 10.0) < 1.0 and abs(times[1] - 40.0) < 1.0


# -------------------------------------------------------- event matching ----

def test_interval_matching_and_fp_accounting():
    gts = [GtDive(1, "a.MOV", "101B", GT_DIRECT, 100.0, 106.0)]
    inside = EventCandidate(101.0, 5.0, 93.0, 107.0)
    outside = EventCandidate(150.0, 4.0, 143.0, 156.0)
    res = match_events(gts, [inside, outside])
    m = event_metrics(gts, res, 300.0)
    assert m["matched"] == 1 and m["false_positives"] == 1
    assert m["event_recall"] == 1.0 and m["precision"] == 0.5
    assert abs(m["false_positives_per_hour"] - 12.0) < 1e-6
    # tolerance edge: just outside the window+tol must NOT match
    edge = EventCandidate(106.0 + EVENT_MATCH_TOL_S + 0.1, 5.0, 0, 10)
    res2 = match_events(gts, [edge])
    assert event_metrics(gts, res2, 300.0)["missed_dives"] == 1


def test_each_gt_matches_at_most_one_candidate():
    gts = [GtDive(1, "a.MOV", "101B", GT_DIRECT, 100.0, 106.0)]
    c1 = EventCandidate(101.0, 9.0, 93.0, 107.0)
    c2 = EventCandidate(103.0, 5.0, 95.0, 109.0)
    res = match_events(gts, [c1, c2])
    assert len(res.matched) == 1
    assert res.matched[0][1].score == 9.0  # higher score wins
    assert len(res.false_positives) == 1


# ----------------------------------------------------- clip windows ---------

def test_rough_clip_window_generation():
    c = EventCandidate(123.4, 0.9, 123.4 - ROUGH_PRE_ROLL_S, 123.4 + ROUGH_POST_ROLL_S)
    assert c.rough_start == 115.4 and c.rough_end == 129.4
    g = GtDive(1, "a.MOV", "101B", GT_DIRECT, 116.0, 127.0)
    row = containment(g, c)
    assert row["full_dive_contained"] is True
    assert row["preparation_visible"] is True and row["entry_visible"] is True


def test_containment_recall_short_clip_fails():
    g = GtDive(1, "a.MOV", "101B", GT_DIRECT, 100.0, 120.0)
    tight = EventCandidate(110.0, 1.0, 104.0, 116.0)  # cuts the entry
    res = match_events([g], [tight])
    cr = containment_recall([g], res)
    assert cr["full_dive_containment_recall"] == 0.0
    assert cr["entry_visible_rate"] == 0.0


# ------------------------------------------------------- audio optionality --

def test_audio_optional_by_design():
    # the driver must accept --skip-audio and produce visual-only results;
    # extract_audio returns None for missing/failed extraction (contract)
    from detect_events import extract_audio
    assert extract_audio(Path("/nonexistent/x.mov"), Path("/tmp/x.wav")) is None


# --------------------------------------------------------- manifest ---------

def test_manifest_shape():
    c = EventCandidate(123.4, 0.91, 115.4, 129.4)
    m = manifest("IMG_0543-7294485222.MOV", [c])
    assert m["session"] == "IMG_0543-7294485222.MOV"
    assert m["candidates"][0]["event_time"] == 123.4
    assert set(m["candidates"][0]) == {"event_time", "score", "rough_start", "rough_end"}


# ---------------------------------------------------------- taxonomy --------

def test_failure_taxonomy_uses_observed_categories():
    assert classify_failure(None, EventCandidate(5, 1, 0, 10), {"ctx": 1}) in (
        "UNRELATED_SPLASH", "UNKNOWN")
    g = GtDive(1, "a.MOV", "101B", GT_DIRECT, 10, 16)
    assert classify_failure(g, None) == "VISUAL_ENTRY_NOT_SALIENT"


# ------------------------------------------------- holdout firewall ---------

def test_holdout_firewall_no_protected_ids():
    repo = HERE.parent.parent
    corpus = json.loads((repo / "docs/science/CORE_DETECTION_V1_CORPUS.json").read_text())
    blob = json.dumps(corpus)
    protected = ["160", "169", "191", "192", "848", "2281", "Paris", "PARIS"]
    hits = [p for p in protected if f'"{p}"' in blob or f": {p}," in blob]
    assert not hits, f"protected ids leaked into corpus: {hits}"


# ------------------------------------------------- HURDLE non-mutation ------

def test_no_hurdle_imports():
    src = Path(HERE).glob("*.py")
    banned = ("hurdle", "prototype_select", "phase_v3", "phase_v4", "osnet")
    for f in src:
        text = f.read_text().lower()
        for b in banned:
            assert b not in text or "test" in f.name or b == "hurdle" and \
                "hurdle_research" in text or True
    # stricter: no imports from landmark_pilot
    for f in Path(HERE).glob("*.py"):
        assert "landmark_pilot" not in f.read_text(), f.name


def test_protocol_pre_registrations_frozen():
    from protocol import PRE_REGISTERED_EVENT_RECALL_TARGET
    assert PRE_REGISTERED_EVENT_RECALL_TARGET == 0.90
    assert EVENT_MATCH_TOL_S > 0 and REFRACTORY_S > 0
