"""DIVE_ANALYZER_FLIGHT_PERCEPTION_SUCCESSOR_V1 — guardrail tests (fast; host artifacts optional)."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fps_media_v1 as fm  # noqa: E402

LOC = fm.DOC / 'localization_annotations_v1'
PROTOCOL_SHA = 'df8cca1021d78a63ed475cab190e76a50d0bdbbe4437114f13dc167b6f6380cf'
HOLDOUT_DIGEST = 'f971294256212070fdae5202db16ca40922a33f84ee732ed00c738e44969392f'
FTR1_DIGEST = '05574219f79ee3adcc85ab4542246c199173176a6b1ac8569f94b836b85f1611'
D5_SHA = '82b420c4583f8271b1eb3429b14dadf0a1e27477249de7b6a0b9d42a788dcf25'
REG = fm.RUNS / 'MODEL_REGISTRY_V1.json'
host = pytest.mark.skipif(not REG.exists(), reason='host artifacts absent')


def test_split_sessions_disjoint_and_unused():
    r = fm.split()['roles']
    hs = set(r['FRESH_FLIGHT_HOLDOUT']['sessions'])
    ts = set(r['TRAIN_NEW_HUMAN_FLIGHT_LABELS']['sessions'])
    vs = set(r['MODEL_SELECTION_VALIDATION']['sessions'])
    used = set(fm.split()['eligibility_authority']['sessions_already_used_by_science'])
    assert not hs & ts and not hs & vs and not ts & vs
    assert not hs & used and not ts & used


def test_protected_firewall():
    for d in ('524', '2555', '2819', '160', '169', '191', '192', '848', '2281', '2584'):
        with pytest.raises(AssertionError):
            fm.assert_allowed(d)
    assert not set(fm.roles()) & (fm.FORBIDDEN - {'524', '2555'})


def _manifest_ok(d, label_digest):
    man = json.loads((d / 'MANIFEST.json').read_text())
    for name, h in man['files'].items():
        assert fm.sha256_file(d / name) == h
    assert hashlib.sha256(json.dumps(man['files'], sort_keys=True).encode()).hexdigest() == man['digest'] == label_digest
    return man


def test_frozen_human_authorities():
    h = _manifest_ok(LOC / 'FLIGHT_GT_HUMAN_V2_HOLDOUT', HOLDOUT_DIGEST)
    t = _manifest_ok(LOC / 'FLIGHT_TRAIN_HUMAN_V1', FTR1_DIGEST)
    assert h['sealed'] and not t['sealed']
    assert set(h['dives']) <= set(fm.dives_with_role('HOLDOUT'))
    assert set(t['dives']) <= set(fm.dives_with_role('TRAIN_NEW'))
    for p in (LOC / 'FLIGHT_GT_HUMAN_V2_HOLDOUT').glob('FGT2H_*_f*.json'):
        a = json.loads(p.read_text())
        assert a['authority'] == 'HUMAN_REVIEWED' and a['method'] == 'human_drawn_blind'


def test_holdout_loader_requires_committed_protocol():
    sys.path.insert(0, str(HERE.parent / 'subject_resolution'))
    import fps_downstream_v1 as D
    with pytest.raises(AssertionError):
        D.load_holdout('0' * 64)
    auth, digest = D.load_holdout(PROTOCOL_SHA)
    assert digest == HOLDOUT_DIGEST and len(auth) == 9


def test_annotation_ui_hides_set():
    import fps_flight_gt_annotation_v2 as A
    assert "k != 'set'" in Path(A.__file__).read_text()
    assert '/frames/' not in A._UI and A._UI.count('ssrc(') == 2


def test_frozen_d5_untouched():
    assert fm.sha256_file(fm.ROOT / 'models/frozen/DIVER_DETECTOR_D5_A_V8N_best.pt') == D5_SHA


@host
def test_training_data_never_holdout_or_protected():
    for ds in (fm.RUNS / 'datasets').iterdir():
        man = json.loads((ds / 'MANIFEST.json').read_text())
        dives = set(man['train_dives']) | set(man['val_dives'])
        assert not dives & set(fm.dives_with_role('HOLDOUT'))
        assert not dives & fm.FORBIDDEN
        assert man['holdout_read'] is False


@host
def test_successor_registered_and_frozen():
    reg = json.loads(REG.read_text())
    s2 = reg['S2_COCOinit_DS1']
    assert s2['status'] == 'EXPERIMENTAL_FROZEN_FOR_HOLDOUT'
    assert fm.sha256_file(s2['path']) == s2['sha256'] == 'd3ba0b035e7a8eb20bb5af66db62984bfb4682075b0c1267677d293e0e9d9c7f'


@host
def test_downstream_parity_with_sealed_fsr():
    a = json.loads((fm.RUNS / 'downstream/D5_FGT1.json').read_text())['dives']
    b = json.loads((fm.PERSO / 'diveanalyzer-flight-search-recovery-v1/runs/flight_search_recovery_v1/final_eval/mine.json').read_text())
    for d in ('1304', '2204', '2223', '2526', '2583', '2839'):
        for k in ('S0_raw_presence', 'S3_pool_recovered', 'first_recovered_rank'):
            assert a[d]['360'][k] == b[d]['all:360'][k]
