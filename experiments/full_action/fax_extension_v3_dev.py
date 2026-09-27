"""FAX V3 development: selected-flight continuation with explicit mixed-edge abstention.

This is a deliberately bounded safety candidate, not a promoted tracker. It
does not read HUMAN labels or diver_id. A broad flight-edge box which can
contain a separate detected body is not a person-specific backward anchor.
"""
from __future__ import annotations

import fax_extension_v1 as V1
import fax_extension_v2_dev as V2

VERSION = 'FULL_ACTION_EXTENSION_V3_DEV'
LOOKBACK_S = .65
MIN_LATERAL_SEPARATION = .105
MAX_COMPONENT_WIDTH_FRACTION = .65
MIN_MIXED_WIDTH = .35


def _edge_mixture(core, floor, pts):
    """Find an independently detected compact body under a broad edge box.

    The two candidate explanations (compact body and the rest of the broad
    detection) remain alternatives. Detection confidence is intentionally
    excluded: 205's target component is low confidence while the neighbor is
    high confidence. This test certifies ambiguity, not either identity.
    """
    edge = min(core)
    edge_box = core[edge]
    if edge_box[2] < MIN_MIXED_WIDTH:
        return None
    evidence = []
    for f in range(edge - 1, -1, -1):
        if pts[edge] - pts[f] > LOOKBACK_S:
            break
        for b in floor[f]:
            if b[2] > MAX_COMPONENT_WIDTH_FRACTION * edge_box[2]:
                continue
            if abs(b[0] - edge_box[0]) < MIN_LATERAL_SEPARATION:
                continue
            if V1.box_iou(b, edge_box) <= 0:
                continue
            evidence.append((f, b))
    # Repeated observations distinguish a person component from one floor
    # false positive; keep the sample identities inspectable in the artifact.
    bins = {}
    for f, b in evidence:
        key = round(b[0] / .04)
        bins.setdefault(key, []).append((f, b))
    sustained = [rows for rows in bins.values()
                 if len(set(f for f, _ in rows)) >= 3]
    if not sustained:
        return None
    rows = max(sustained, key=lambda xs: len(set(f for f, _ in xs)))
    return {'reason': 'MIXED_FLIGHT_EDGE', 'edge_frame': edge,
            'edge_time': pts[edge], 'edge_box': list(edge_box[:4]),
            'component_frames': sorted(set(f for f, _ in rows)),
            'component_example': list(max(rows, key=lambda x: x[1][4])[1][:4]),
            'alternatives': ['compact_component', 'remaining_group_body', 'NULL']}


def build_track(dive, rep, ft0, ft1, pool_path_nodes, Latt, Floor, pts):
    original = {f: tuple(float(v) for v in Latt[f][j]) for f, j in pool_path_nodes
                if ft0 - 1e-9 <= pts[f] <= ft1 + 1e-9}
    assert len(original) >= 2
    mixture = _edge_mixture(original, Floor, pts)
    base = V2.build_track(dive, rep, ft0, ft1, pool_path_nodes, Latt, Floor, pts)
    if mixture:
        # A mixed flight edge is an uncertainty interval, not a chosen person.
        # Preserve the selected FSR flight provenance and all unrelated paths.
        # A later narrower box alone does not prove which component survived
        # the merge. Keep the entire selected path uncertain until independent
        # person-specific evidence exists; this candidate has no such proof.
        edge = mixture['edge_frame']
        mixture['resolved_frame'] = None
        mixture['resolved_time'] = None
        mixture['last_selected_frame'] = max(original)
        mixture['last_selected_time'] = pts[max(original)]
        mixture['selected_flight_source_boxes'] = len(original)
        for f in list(base['trajectory']):
            if int(f) < edge:
                del base['trajectory'][f]
            else:
                del base['trajectory'][f]
        base['backward'] = {'n_linked': 0, 'bridged': [],
                            'stop': {'reason': 'MIXED_FLIGHT_EDGE',
                                     'at_f': edge, 'at_t': pts[edge],
                                     'alternatives': mixture['alternatives']}}
    base['version'] = VERSION
    base['uncertainty'] = [mixture] if mixture else []
    return base
