"""Event matching, metrics, rough-clip containment, manifest, taxonomy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from detect_events import EventCandidate
from protocol import (
    EVENT_MATCH_TOL_S,
    FAILURE_CATEGORIES,
    GT_DIRECT,
    GT_RECOVERED,
)


@dataclass
class GtDive:
    dive_id: int | None
    clip: str
    dive_code: str | None
    authority: str                    # GT_DIRECT / GT_RECOVERED / GT_WEAK
    start: float
    end: float


@dataclass
class MatchResult:
    matched: list = field(default_factory=list)   # (gt, candidate)
    missed: list = field(default_factory=list)    # gt with no candidate
    false_positives: list = field(default_factory=list)


def match_events(gts: list[GtDive], cands: list[EventCandidate],
                 tol_s: float = EVENT_MATCH_TOL_S) -> MatchResult:
    """Interval semantics: candidate matches a GT dive when the candidate time
    falls within [gt.start - tol, gt.end + tol]. Each GT matches at most one
    candidate (highest score); each candidate at most one GT."""
    res = MatchResult()
    used_c: set[int] = set()
    pairs = []
    for gi, g in enumerate(gts):
        for ci, c in enumerate(cands):
            if g.start - tol_s <= c.event_time <= g.end + tol_s:
                pairs.append((gi, ci, c.score))
    pairs.sort(key=lambda p: -p[2])
    g_used: set[int] = set()
    for gi, ci, _ in pairs:
        if gi in g_used or ci in used_c:
            continue
        g_used.add(gi)
        used_c.add(ci)
        res.matched.append((gts[gi], cands[ci]))
    for gi, g in enumerate(gts):
        if gi not in g_used:
            res.missed.append(g)
    for ci, c in enumerate(cands):
        if ci not in used_c:
            res.false_positives.append(c)
    return res


def event_metrics(gts: list[GtDive], res: MatchResult,
                  session_duration_s: float) -> dict:
    primary = [g for g in gts if g.authority in (GT_DIRECT, GT_RECOVERED)]
    matched_primary = [g for g, _ in res.matched
                       if g.authority in (GT_DIRECT, GT_RECOVERED)]
    n = len(primary)
    recall = (len(matched_primary) / n) if n else None
    n_c = len(res.matched) + len(res.false_positives)
    precision = (len(matched_primary) / n_c) if n_c else None
    hours = session_duration_s / 3600.0
    return {
        "gt_dives_primary": n,
        "event_recall": recall,
        "missed_dives": len(res.missed),
        "matched": len(matched_primary),
        "candidates_total": n_c,
        "false_positives": len(res.false_positives),
        "false_positives_per_session": len(res.false_positives),
        "false_positives_per_hour": (len(res.false_positives) / hours) if hours else None,
        "precision": precision,
    }


def timing_errors(res: MatchResult) -> dict | None:
    """Median/p90 |candidate time - GT window center| for matched events.
    With coarse GT windows this is diagnostic only."""
    errs = []
    for g, c in res.matched:
        if g.authority in (GT_DIRECT, GT_RECOVERED):
            center = (g.start + g.end) / 2.0
            errs.append(abs(c.event_time - center))
    if not errs:
        return None
    return {
        "median_abs_error_vs_window_center_s": float(np.median(errs)),
        "p90_abs_error_vs_window_center_s": float(np.percentile(errs, 90)),
    }


def containment(g: GtDive, c: EventCandidate) -> dict:
    """Full-dive containment of the rough clip window vs the GT window."""
    contained = c.rough_start <= g.start and c.rough_end >= g.end
    entry_visible = c.rough_end >= g.end - 0.5   # clip reaches the dive tail
    prep_visible = c.rough_start <= g.start + 0.5
    excess = (c.rough_end - c.rough_start) - (g.end - g.start)
    return {
        "full_dive_contained": bool(contained),
        "preparation_visible": bool(prep_visible),
        "entry_visible": bool(entry_visible),
        "excess_duration_s": float(excess),
    }


def containment_recall(gts: list[GtDive], res: MatchResult) -> dict | None:
    rows = [containment(g, c) for g, c in res.matched
            if g.authority in (GT_DIRECT, GT_RECOVERED)]
    if not rows:
        return None
    n = len(rows)
    return {
        "matched_evaluated": n,
        "full_dive_containment_recall":
            sum(r["full_dive_contained"] for r in rows) / n,
        "entry_visible_rate": sum(r["entry_visible"] for r in rows) / n,
        "preparation_visible_rate": sum(r["preparation_visible"] for r in rows) / n,
        "median_excess_duration_s":
            float(np.median([r["excess_duration_s"] for r in rows])),
    }


def manifest(session: str, cands: list[EventCandidate]) -> dict:
    return {
        "session": session,
        "candidates": [
            {
                "event_time": round(c.event_time, 3),
                "score": round(c.score, 6),
                "rough_start": round(c.rough_start, 3),
                "rough_end": round(c.rough_end, 3),
            }
            for c in cands
        ],
    }


def classify_failure(g: GtDive | None, c: EventCandidate | None,
                     feat_context: dict | None = None) -> str:
    """Failure taxonomy. Only observed, evidence-backed categories are used;
    anything not clearly explained stays UNKNOWN."""
    if g is None and c is not None:
        return "UNRELATED_SPLASH" if feat_context else "UNKNOWN"
    if g is not None and c is None:
        return "VISUAL_ENTRY_NOT_SALIENT"
    return "UNKNOWN"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))
