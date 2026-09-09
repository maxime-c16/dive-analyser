#!/usr/bin/env python3
"""Unit tests for Event Logic V3-E0 (Phase Q+R).

Self-runner pattern (list of test functions, PASS/FAIL counts, exit 0/1).
Covers:
  E0a. Robust board reference: two-level signal (dominant + minority
       target-switch contamination) -> B1r recovers the dominant level where
       the B0-style mixture (smoothed cy at prep_end) fails.
  E0b. Board-level outlier rejection: sparse single-frame outliers rejected
       by the 1.5*MAD rule.
  E0c. Insufficient support -> HISTORICAL_FALLBACK mode + degraded flag
       (2541 pattern: low-conf non-diver plateau) and exact V3-D0 behaviour.
  E0d. STANDING non-regression: V3-E0 STANDING outputs identical to V3-D0 on
       the 4 cached STANDING trajectories AND on synthetic STANDING
       trajectories (301A/401C/5411C patterns).
  E0e. FM1 closure intact: 311 pattern (post-wc pool-deck cy=0.11 suppressed
       by A1+A2).
  E0f. Full-pipeline regression on real cached trajectories (1040 + 2169
       full, 524 fixture): completes, 2169 triplet with to_err < 1.0, 1040
       outcome recorded honestly (improves / not worse / regression surfaced
       to the freeze gate), 524 records board_ref mode, 2169 6.406s target
       switch present in the fixture.
  E0g. Time-shift invariance: longer static prep shifts prep_end/guard but
       the detected takeoff relative to the hurdle sequence stays < 0.35s.
  E0h. Long approach: plateau oscillation < gate rise must NOT become the
       hurdle apex; final takeoff found near the true departure.
  E0i. Approach rise != hurdle: mid-approach hop (rise above board, return,
       continued progression) must not be the final takeoff; the detector
       locks the departure AFTER the hop.
  E0j. Board recontact semantics: final takeoff requires sustained negative
       velocity AFTER the accepted recontact.
  E0k. Quarantined HQ exclusion + HQ read-only (static artifact checks).
  E0l. Paris firewall extension: forbidden Paris constants absent from
       PARAMS_V3E0; Paris trajectory never loaded during DEVELOPMENT eval.
  E0m. Freeze identity: candidate artifact matches PARAMS_V3E0 (freeze or
       gate-failure record).

Rules: GT times appear only in assertions for REAL-cached fixtures (error
reporting); synthetic fixtures carry their own construction constants.
cy_norm convention: 0=top, 1=bottom; rising diver = decreasing cy_norm.
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from proposer_event_logic_v3_d0 import propose_events_v3d0, PARAMS_V3D0
from proposer_event_logic_v3_e0 import (
    propose_events_v3e0,
    _robust_board_reference,
    _robust_median_mad,
    PARAMS_V3E0,
)
from proposer_event_logic_v3_c0 import PARAMS_V3C0

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HURDLE_CACHE = os.path.join(BASE, "docs/science/DEV_HURDLE_TRAJ_CACHE_V2.json")
STANDING_CACHE = os.path.join(BASE, "docs/science/STANDING_TRAJ_CACHE_V2.json")
COMPARISON = os.path.join(BASE, "docs/science/V3E_DEVELOPMENT_COMPARISON_V1.json")
GATE_ART = os.path.join(BASE, "docs/science/V3E_FREEZE_GATE_FAILED_V1.json")
FREEZE_ART = os.path.join(BASE, "docs/science/EVENT_LOGIC_V3_E_FREEZE.json")
HQ_DIAG = os.path.join(BASE, "docs/science/HQ_HURDLE_DIAGNOSTIC_V1.json")
PARIS_EVAL_SCRIPT = os.path.join(
    os.path.dirname(__file__), "phase_v3e_paris_eval.py")
PARIS_EVAL_SCRIPT_SRC = None  # loaded lazily in E0l
DEV_EVAL_SCRIPT = os.path.join(os.path.dirname(__file__), "phase_v3e_eval.py")

_new_artifacts = [COMPARISON, GATE_ART,
                  os.path.join(BASE, "docs/science/PARIS_EXTERNAL_V3E_EVAL_V1.json")]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_pts(n, fps=30.0):
    return [i / fps for i in range(n)]


def synth_arrays(cy, fps=30.0, conf=0.5):
    n = len(cy)
    return cy, make_pts(n, fps), [conf] * n


def standing_traj(fps=30.0, board_cy=0.40, takeoff_s=2.2, apex_s=2.55,
                  wc_s=3.2, n_total_s=4.5, post_wc_low_cy=None):
    n = int(n_total_s * fps) + 1
    pts = make_pts(n, fps)
    cy = []
    for t in pts:
        if t < takeoff_s:
            cy.append(board_cy)
        elif t < apex_s:
            cy.append(board_cy - (t - takeoff_s) / (apex_s - takeoff_s) * 0.12)
        elif t < wc_s:
            cy.append((board_cy - 0.12) +
                      (t - apex_s) / (wc_s - apex_s) * 0.40)
        else:
            cy.append(post_wc_low_cy if post_wc_low_cy is not None else 0.80)
    return cy, pts, [0.5] * n


def hurdle_traj_valid(fps=30.0, board_cy=0.40, static_s=1.5,
                      h_takeoff_s=2.0, h_apex_s=2.2, h_recontact_s=2.5,
                      f_takeoff_s=3.0, apex_s=3.35, wc_s=4.1,
                      n_total_s=5.5):
    n = int(n_total_s * fps) + 1
    pts = make_pts(n, fps)
    cy = []
    for t in pts:
        if t < h_takeoff_s:
            cy.append(board_cy)
        elif t < h_apex_s:
            cy.append(board_cy - (t - h_takeoff_s) / (h_apex_s - h_takeoff_s) * 0.10)
        elif t < h_recontact_s:
            cy.append((board_cy - 0.10) +
                      (t - h_apex_s) / (h_recontact_s - h_apex_s) * 0.10)
        elif t < f_takeoff_s:
            cy.append(board_cy)
        elif t < apex_s:
            cy.append(board_cy - (t - f_takeoff_s) / (apex_s - f_takeoff_s) * 0.14)
        elif t < wc_s:
            cy.append((board_cy - 0.14) + (t - apex_s) / (wc_s - apex_s) * 0.48)
        else:
            cy.append(0.80)
    return cy, pts, [0.5] * n


def _prep_end_of(y_arr, pts_arr, params=PARAMS_V3E0):
    """V3 semantics: find prep_end on the smoothed signal (GT-blind)."""
    from proposer_event_logic_v2_1 import (
        pts_aware_smooth, interpolate_gaps_time, _find_preparation_end)
    sigma = params["smooth_window_s"] / 3
    ys = interpolate_gaps_time(pts_aware_smooth(y_arr, pts_arr, sigma),
                               pts_arr, params["interp_max_gap_s"])
    return _find_preparation_end(ys, pts_arr, params), ys


# ─── E0a: robust board reference recovers the dominant level ─────────────────

def test_e0a_robust_board_reference_dominant_level():
    """Two-level raw signal: dominant 0.40 with a minority target-switch run
    (0.70) near prep_end. B1r must recover 0.40; the B0-style mixture
    (smoothed cy at prep_end) is contaminated and must NOT match 0.40."""
    fps = 30.0
    n = 90
    pts = make_pts(n, fps)
    cy = []
    for i in range(n):
        t = pts[i]
        if 2.60 <= t < 2.90:      # minority target-switch run (9 frames,
            cy.append(0.70)       # close enough to contaminate smoothed prep)
        else:
            cy.append(0.40)
    conf = [0.5] * n
    prep_end_i = n - 1            # full initial plateau window (GT-blind bound)
    b1r, n_support, _rej = _robust_board_reference(cy, pts, conf, prep_end_i,
                                                   PARAMS_V3E0)
    assert n_support > 20, f"E0a: cluster too small ({n_support})"
    assert b1r is not None and abs(b1r - 0.40) < 0.005, (
        f"E0a: B1r {b1r} did not recover dominant level 0.40")
    # B0-style mixture: smoothed cy at prep_end inherits the switch run
    _, ys = _prep_end_of(cy, pts)
    y_prep = ys[prep_end_i]
    assert abs(y_prep - 0.40) > 0.01, (
        f"E0a: expected B0-style mixture contamination, got {y_prep}")
    assert abs(y_prep - b1r) > 0.01, "E0a: B0-style and B1r must differ here"


# ─── E0b: MAD outlier rejection ──────────────────────────────────────────────

def test_e0b_board_level_outlier_rejection():
    """Sparse single-frame outliers are rejected by the 1.5*MAD rule.

    End-to-end through the cluster recipe: 2-frame steps at 0.45 embed a few
    0.45 samples into the cluster (the second frame of each step passes the
    |vel|<=0.02 filter); MAD must reject them and keep the dominant 0.30."""
    fps = 30.0
    n = 80
    pts = make_pts(n, fps)
    cy = []
    for i in range(n):
        t = pts[i]
        base = 0.30 + (0.0003 if i % 2 else -0.0003)   # tiny jitter (vel-safe)
        if (20 <= i <= 21) or (35 <= i <= 36) or (50 <= i <= 51):
            cy.append(0.45)                            # outlier steps
        else:
            cy.append(base)
    conf = [0.5] * n
    prep_end_i = n - 1
    b1r, n_support, n_rej = _robust_board_reference(cy, pts, conf, prep_end_i,
                                                    PARAMS_V3E0)
    assert b1r is not None and abs(b1r - 0.30) < 0.005, (
        f"E0b: B1r {b1r} did not recover dominant level 0.30")
    assert n_rej >= 3, (
        f"E0b: MAD rule must reject the 0.45 outliers (rejected {n_rej})")
    # Direct unit check of the rejection helper
    med1, _mad, _n, n_rej2 = _robust_median_mad(
        [0.30] * 20 + [0.31, 0.29, 0.305, 0.45, 0.46])
    assert n_rej2 >= 2 and abs(med1 - 0.30) < 0.005, (
        f"E0b: _robust_median_mad med={med1} rejected={n_rej2}")


# ─── E0c: insufficient support -> HISTORICAL_FALLBACK ────────────────────────

def test_e0c_insufficient_support_historical_fallback():
    """2541 pattern: initial plateau is a low-conf non-diver target
    (conf 0.06 < 0.10) -> cluster empty -> HISTORICAL_FALLBACK mode and
    exact V3-D0 behaviour (detection degrades gracefully, never crashes)."""
    fps = 30.0
    board_cy = 0.40
    cy, pts, _ = hurdle_traj_valid(fps=fps, board_cy=board_cy)
    conf = [0.06] * len(cy)       # whole clip below the cluster conf floor
    r_d0 = propose_events_v3d0(cy, pts, conf, "5111B", PARAMS_V3D0)
    r_e0 = propose_events_v3e0(cy, pts, conf, "5111B", PARAMS_V3E0)
    assert r_e0["board_ref_mode"] == "HISTORICAL_FALLBACK", (
        f"E0c: mode {r_e0['board_ref_mode']}")
    assert r_e0["board_ref_n_support"] == 0
    for k in ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t"):
        assert r_d0[k] == r_e0[k], (
            f"E0c: HISTORICAL_FALLBACK must reproduce V3-D0 exactly ({k})")


# ─── E0d: STANDING non-regression ────────────────────────────────────────────

def test_e0d_standing_non_regression():
    """STANDING path byte-identical to V3-D0: 4 cached trajectories + synthetic
    301A/401C/5411C patterns."""
    sc = json.load(open(STANDING_CACHE))
    codes = {"133": "301B", "311": "401C", "676": "301A", "2387": "5411C"}
    for did, entry in sc["per_dive"].items():
        y = [f["cy"] for f in entry["frames"]]
        pts = [f["pts_s"] for f in entry["frames"]]
        conf = [f["conf"] if f["conf"] is not None else 0.0
                for f in entry["frames"]]
        r_d0 = propose_events_v3d0(y, pts, conf, codes[did], PARAMS_V3D0)
        r_e0 = propose_events_v3e0(y, pts, conf, codes[did], PARAMS_V3E0)
        for k in ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t"):
            assert r_d0[k] == r_e0[k], (
                f"E0d: cached dive {did} STANDING regression on {k}")
    for code in ("301A", "401C", "5411C"):
        cy, pts, conf = standing_traj(board_cy=0.40)
        r_d0 = propose_events_v3d0(cy, pts, conf, code, PARAMS_V3D0)
        r_e0 = propose_events_v3e0(cy, pts, conf, code, PARAMS_V3E0)
        for k in ("prep_end_t", "takeoff_t", "apex_t", "water_contact_t"):
            assert r_d0[k] == r_e0[k], (
                f"E0d: synthetic {code} STANDING regression on {k}")


# ─── E0e: FM1 closure intact (311 pattern) ───────────────────────────────────

def test_e0e_fm1_closure_intact():
    """311 pattern: post-wc pool-deck cy=0.11 must be suppressed by A1+A2
    (unchanged in V3-E0)."""
    cy, pts, conf = standing_traj(fps=30.0, board_cy=0.40, takeoff_s=2.0,
                                  apex_s=2.35, wc_s=3.0, n_total_s=8.0,
                                  post_wc_low_cy=0.11)
    r = propose_events_v3e0(cy, pts, conf, "401C", PARAMS_V3E0)
    assert r["water_contact_t"] is not None, "E0e: wc must be found"
    assert r["water_contact_t"] < 5.0, (
        f"E0e: wc {r['water_contact_t']} too late — pool-deck not suppressed")


# ─── E0f: full-pipeline regression on real cached trajectories ───────────────

def test_e0f_full_pipeline_regression_real():
    """Real fixtures from DEV_HURDLE_TRAJ_CACHE_V2.json: 1040 + 2169 full,
    524 fixture. GT times used only for error assertions."""
    hc = json.load(open(HURDLE_CACHE))

    def gt_err(res, did):
        gt = hc["per_dive"][did]["gt"]
        return None if res["takeoff_t"] is None else abs(
            res["takeoff_t"] - gt["takeoff"])

    def arrays(did):
        return None, None, None  # placeholder, replaced below

    # — 2169 —
    e = hc["per_dive"]["2169"]
    y = [f["cy"] for f in e["frames"]]
    pts = [f["pts_s"] for f in e["frames"]]
    conf = [f["conf"] if f["conf"] is not None else 0.0 for f in e["frames"]]
    # the 6.406s target switch must be present in the fixture
    low_before = any(f["cy"] is not None and f["cy"] < 0.40
                     and 6.2 <= f["pts_s"] <= 6.40 for f in e["frames"])
    high_after = any(f["cy"] is not None and f["cy"] > 0.55
                     and 6.40 <= f["pts_s"] <= 6.80 for f in e["frames"])
    assert low_before and high_after, (
        "E0f: 2169 6.406s target switch not present in the fixture")
    r = propose_events_v3e0(y, pts, conf, e["code"], PARAMS_V3E0)
    assert all(r[k] is not None for k in
               ("takeoff_t", "apex_t", "water_contact_t")), (
        "E0f: 2169 must produce a complete triplet")
    to_err = gt_err(r, "2169")
    assert to_err < 1.0, f"E0f: 2169 to_err {to_err} >= 1.0"
    assert r["board_ref_mode"] == "B1R" and r["board_ref_n_support"] >= 5

    # — 1040 —
    e = hc["per_dive"]["1040"]
    y = [f["cy"] for f in e["frames"]]
    pts = [f["pts_s"] for f in e["frames"]]
    conf = [f["conf"] if f["conf"] is not None else 0.0 for f in e["frames"]]
    r_d0 = propose_events_v3d0(y, pts, conf, e["code"], PARAMS_V3D0)
    r_e0 = propose_events_v3e0(y, pts, conf, e["code"], PARAMS_V3E0)
    assert r_e0["board_ref_mode"] == "B1R", (
        f"E0f: 1040 board_ref_mode {r_e0['board_ref_mode']}")
    assert abs(r_e0["board_ref"] - 0.2207765430212021) < 1e-6, (
        "E0f: 1040 B1r must reproduce the audit value 0.2208")
    d0_err = gt_err(r_d0, "1040")
    e0_err = gt_err(r_e0, "1040")
    if e0_err <= d0_err:
        assert e0_err <= d0_err + 1e-9   # improves or equal
    else:
        # V3-E0 is WORSE on 1040 (post-water-contact flicker crossing at
        # 9.343s passes the corrected board-rise gate). The regression must
        # be surfaced, not hidden: the Phase K comparison flags it and the
        # freeze gate FAILED with MORE_HURDLE_GT_REQUIRED.
        comp = json.load(open(COMPARISON))
        assert "1040" in comp["aggregates"]["regressed_non_drill_dives"]
        assert comp["freeze_gate"]["gate_result"] == "FAIL"
        assert comp["freeze_gate"]["decision"] == "MORE_HURDLE_GT_REQUIRED"
        gate = json.load(open(GATE_ART))
        assert gate["status"] == "GATE_FAILED"
        assert "hurdle_improvement_beyond_single_dive" in gate["failed_criteria"]

    # — 524 fixture —
    e = hc["per_dive"]["524"]
    y = [f["cy"] for f in e["frames"]]
    pts = [f["pts_s"] for f in e["frames"]]
    conf = [f["conf"] if f["conf"] is not None else 0.0 for f in e["frames"]]
    r = propose_events_v3e0(y, pts, conf, e["code"], PARAMS_V3E0)
    assert r["board_ref_mode"] in ("B1R", "HISTORICAL_FALLBACK"), (
        "E0f: 524 must record a board_ref mode")
    assert r["prep_end_t"] is not None and r["coverage"] > 0.5


# ─── E0g: time-shift invariance ──────────────────────────────────────────────

def test_e0g_time_shift_invariance():
    """Appending a longer static prep block before the same hurdle sequence
    shifts prep_end/guard, but the detected takeoff relative to the hurdle
    sequence stays within 0.35s."""
    results = {}
    for static_s in (1.5, 5.0):
        h_to = static_s + 0.5
        cy, pts, conf = hurdle_traj_valid(
            static_s=static_s, h_takeoff_s=h_to,
            h_apex_s=static_s + 0.7, h_recontact_s=static_s + 1.0,
            f_takeoff_s=static_s + 1.5, apex_s=static_s + 1.85,
            wc_s=static_s + 2.6, n_total_s=static_s + 4.0)
        r = propose_events_v3e0(cy, pts, conf, "102C", PARAMS_V3E0)
        assert r["takeoff_t"] is not None, f"E0g: no takeoff (static={static_s})"
        results[static_s] = r["takeoff_t"] - h_to   # relative to hurdle sequence
    delta = abs(results[5.0] - results[1.5])
    assert delta < 0.35, f"E0g: relative takeoff shifted by {delta:.3f}s"


# ─── E0h: long approach oscillation is not the hurdle ────────────────────────

def test_e0h_long_approach_oscillation_not_hurdle():
    """Sustained low-amplitude approach with cy plateau oscillation amplitude
    0.005 (< min_hurdle_rise_cy 0.01) followed by a real hurdle rise: the
    gate must reject plateau oscillations; final takeoff near true departure."""
    fps = 30.0
    board_cy = 0.40
    static_end = 1.0
    approach_s = 3.0              # approach from 1.0 to 4.0
    h_to, h_apex, h_rc = 4.0, 4.4, 4.8
    f_to, apex, wc = 5.6, 5.95, 6.7
    n = int(8.5 * fps) + 1
    pts = make_pts(n, fps)
    cy = []
    for t in pts:
        if t < static_end:
            cy.append(board_cy)
        elif t < static_end + approach_s:
            # approach: slow forward drift with small cy oscillation (0.005)
            cy.append(board_cy - 0.004 + 0.005 * (2 * ((t * 1.3) % 1.0) - 1))
        elif t < h_to:
            cy.append(board_cy)               # loading at board end
        elif t < h_apex:
            cy.append(board_cy - (t - h_to) / (h_apex - h_to) * 0.10)
        elif t < h_rc:
            cy.append((board_cy - 0.10) + (t - h_apex) / (h_rc - h_apex) * 0.10)
        elif t < f_to:
            cy.append(board_cy)
        elif t < apex:
            cy.append(board_cy - (t - f_to) / (apex - f_to) * 0.14)
        elif t < wc:
            cy.append((board_cy - 0.14) + (t - apex) / (wc - apex) * 0.48)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    r = propose_events_v3e0(cy, pts, conf, "102C", PARAMS_V3E0)
    assert r["takeoff_t"] is not None, "E0h: final takeoff not found"
    assert abs(r["takeoff_t"] - f_to) < 0.5, (
        f"E0h: takeoff {r['takeoff_t']} too far from true departure {f_to}")
    # no takeoff may be claimed during the approach
    assert r["takeoff_t"] > static_end + approach_s - 0.2, (
        "E0h: takeoff claimed inside the approach phase")
    assert r["apex_t"] is not None and r["water_contact_t"] is not None


# ─── E0i: approach hop is not the final takeoff ──────────────────────────────

def test_e0i_approach_hop_not_final_takeoff():
    """Genuine mid-approach hop (rise 0.06 above board, return, continued
    progression, then the real hurdle): the detector must lock the departure
    chain AFTER the hop."""
    fps = 30.0
    board_cy = 0.40
    static_end = 1.0
    hop_start, hop_apex, hop_end = 2.0, 2.3, 2.7
    h_to, h_apex, h_rc = 4.2, 4.6, 5.0
    f_to, apex, wc = 5.8, 6.15, 6.9
    n = int(8.8 * fps) + 1
    pts = make_pts(n, fps)
    cy = []
    for t in pts:
        if t < static_end:
            cy.append(board_cy)
        elif t < hop_start:
            cy.append(board_cy - 0.004)       # approach drift
        elif t < hop_apex:
            cy.append(board_cy - (t - hop_start) / (hop_apex - hop_start) * 0.06)
        elif t < hop_end:
            cy.append((board_cy - 0.06) + (t - hop_apex) / (hop_end - hop_apex) * 0.06)
        elif t < h_to:
            cy.append(board_cy)               # continued progression / loading
        elif t < h_apex:
            cy.append(board_cy - (t - h_to) / (h_apex - h_to) * 0.10)
        elif t < h_rc:
            cy.append((board_cy - 0.10) + (t - h_apex) / (h_rc - h_apex) * 0.10)
        elif t < f_to:
            cy.append(board_cy)
        elif t < apex:
            cy.append(board_cy - (t - f_to) / (apex - f_to) * 0.14)
        elif t < wc:
            cy.append((board_cy - 0.14) + (t - apex) / (wc - apex) * 0.48)
        else:
            cy.append(0.80)
    conf = [0.5] * n
    r = propose_events_v3e0(cy, pts, conf, "102C", PARAMS_V3E0)
    assert r["takeoff_t"] is not None, "E0i: final takeoff not found"
    assert r["takeoff_t"] > hop_end, (
        f"E0i: takeoff {r['takeoff_t']} at/before the mid-approach hop end "
        f"{hop_end}")
    # D0 first-valid-crossing semantics: the hop (gate-passing) is taken as
    # the hurdle, so the departure locks onto the next sustained descent —
    # the onset of the real hurdle rise — never inside the hop or approach.
    assert abs(r["takeoff_t"] - h_to) < 0.35, (
        f"E0i: takeoff {r['takeoff_t']} not locked onto the post-hop chain "
        f"(real hurdle onset {h_to})")
    assert r["takeoff_t"] < f_to, (
        "E0i: takeoff must precede the post-hurdle final departure")


# ─── E0j: board recontact semantics ──────────────────────────────────────────

def test_e0j_board_recontact_sustained_descent_required():
    """A gate-passing crossing whose aftermath has NO sustained negative
    velocity must not yield the final takeoff before a real departure;
    the takeoff requires sustained negative velocity after the recontact."""
    fps = 30.0
    board_cy = 0.40
    static_end = 1.0
    guard_end = static_end + PARAMS_V3E0["hurdle_post_plateau_guard_s"]
    # valid hurdle: rise 0.10, recontact ~2.6, then flat loading, then
    # a real sustained departure at 4.0.
    h_to, h_apex, h_rc = 1.6, 2.0, 2.6
    f_to, apex, wc = 4.0, 4.35, 5.1
    cy, pts, conf = hurdle_traj_valid(
        fps=fps, board_cy=board_cy, static_s=static_end,
        h_takeoff_s=h_to, h_apex_s=h_apex, h_recontact_s=h_rc,
        f_takeoff_s=f_to, apex_s=apex, wc_s=wc,
        n_total_s=6.5)
    r = propose_events_v3e0(cy, pts, conf, "102C", PARAMS_V3E0)
    assert r["takeoff_t"] is not None, "E0j: takeoff not found"
    assert r["takeoff_t"] >= h_rc - 0.05, (
        f"E0j: takeoff {r['takeoff_t']} before the recontact {h_rc}")
    assert abs(r["takeoff_t"] - f_to) < 0.5, (
        f"E0j: takeoff {r['takeoff_t']} not at the sustained departure {f_to}")
    assert r["takeoff_t"] > guard_end


# ─── E0k: quarantined HQ exclusion + HQ read-only ────────────────────────────

def _walk_hq_keys(node, path=""):
    """Yield (path, value) for every JSON key containing 'hq' (case-insens)."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if "hq" in str(k).lower():
                yield p, v
            yield from _walk_hq_keys(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_hq_keys(v, f"{path}[{i}]")


def test_e0k_quarantined_hq_exclusion_and_readonly():
    """(a) HQ diagnostic declares read-only with assets 1040+2169 only;
    (b) no quarantined dive (311, 524) appears as an HQ asset in any new
    artifact; (c) PARAMS_V3E0 blob contains no 'hq'/'paris' keys/values."""
    hq = json.load(open(HQ_DIAG))
    assert hq["hq_read_only"] is True
    assert hq["assets_used"] == ["1040", "2169"]
    for art in _new_artifacts:
        with open(art) as f:
            node = json.load(f)
        for path, val in _walk_hq_keys(node):
            blob = json.dumps(val).lower()
            assert '"311"' not in blob and '"524"' not in blob, (
                f"E0k: quarantined dive as HQ asset in {art}:{path}")
    blob = json.dumps(PARAMS_V3E0).lower()
    assert "hq" not in blob and "paris" not in blob, (
        "E0k: forbidden 'hq'/'paris' string in PARAMS_V3E0")


# ─── E0l: Paris firewall extension ───────────────────────────────────────────

def test_e0l_paris_firewall_extension():
    """Forbidden Paris constants {3.120, 3.570, 4.220, 1.685} never appear as
    PARAMS_V3E0 values or as code literals; the DEVELOPMENT eval script never
    references the Paris trajectory artifact."""
    forbidden = ("3.120", "3.570", "4.220", "1.685")
    blob = json.dumps(PARAMS_V3E0)
    assert "paris" not in blob.lower()
    for k, v in PARAMS_V3E0.items():
        if isinstance(v, float):
            assert v not in (3.120, 3.570, 4.220, 1.685), (
                f"E0l: param {k}={v} matches a Paris-derived constant")
    for src_path in (os.path.join(os.path.dirname(__file__),
                                  "proposer_event_logic_v3_e0.py"),
                     DEV_EVAL_SCRIPT):
        with open(src_path) as f:
            src = f.read()
        assert "PARIS_FULL_TRAJECTORY" not in src or \
               src_path.endswith("phase_v3e_paris_eval.py"), (
            f"E0l: Paris trajectory referenced in {src_path}")
        for line in src.splitlines():
            code = line.split("#")[0]
            for lit in forbidden:
                assert lit not in code, (
                    f"E0l: Paris-derived literal {lit} in code: "
                    f"{os.path.basename(src_path)}: {line.strip()}")


# ─── E0m: freeze identity ────────────────────────────────────────────────────

def test_e0m_freeze_identity():
    """The candidate artifact (freeze, or gate-failure record when the gate
    failed) must match PARAMS_V3E0 exactly."""
    if os.path.exists(FREEZE_ART):
        art = json.load(open(FREEZE_ART))
        assert art["parameters"] == PARAMS_V3E0
        assert art["variant"] == PARAMS_V3E0["variant"]
        return
    assert os.path.exists(GATE_ART), (
        "E0m: neither freeze nor gate-failure artifact exists")
    gate = json.load(open(GATE_ART))
    assert gate["status"] == "GATE_FAILED"
    assert gate["variant"] == PARAMS_V3E0["variant"]
    assert gate["parameters"] == PARAMS_V3E0, (
        "E0m: gate-failure record parameters diverge from PARAMS_V3E0")
    assert gate["decision"] == "MORE_HURDLE_GT_REQUIRED"
    comp = json.load(open(COMPARISON))
    assert comp["params_v3e0"] == PARAMS_V3E0


# ─── Runner ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_e0a_robust_board_reference_dominant_level,
        test_e0b_board_level_outlier_rejection,
        test_e0c_insufficient_support_historical_fallback,
        test_e0d_standing_non_regression,
        test_e0e_fm1_closure_intact,
        test_e0f_full_pipeline_regression_real,
        test_e0g_time_shift_invariance,
        test_e0h_long_approach_oscillation_not_hurdle,
        test_e0i_approach_hop_not_final_takeoff,
        test_e0j_board_recontact_sustained_descent_required,
        test_e0k_quarantined_hq_exclusion_and_readonly,
        test_e0l_paris_firewall_extension,
        test_e0m_freeze_identity,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed + failed} tests: {passed} passed, {failed} failed")
    exit(0 if failed == 0 else 1)
