from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.services.technique_history import (
    Attribution, Context, Episode, OrderKey, family, recorded_side,
    resolve_context, resolve_use, validate_pair,
)

C = Context(1, 1, '103', 'springboard', '3', 'B', False)


def key(n):
    return OrderKey(datetime(2026, 1, 1) + timedelta(seconds=n), n)


def episode(id=1, **kwargs):
    return replace(Episode(id, C, '103', key(10), id), **kwargs)


def test_family_exception_gap_and_resume():
    broad = episode(scope='1', technique_id=10)
    exact = episode(2, start=key(20), end=key(30))
    assert resolve_context(C, key(25), [broad, exact]).technique_id == 2
    assert resolve_context(C, key(30), [broad, exact]).technique_id == 10
    gap = replace(exact, gap=True)
    assert resolve_context(C, key(25), [broad, gap]).source == 'gap'
    assert resolve_context(C, key(25), [replace(broad, gap=True), exact]).technique_id == 2


def test_unknown_before_history_and_approximation():
    e = episode(uncertain_until=key(20))
    assert resolve_context(C, key(9), [e]).state == 'unrecorded'
    assert resolve_context(C, key(15), [e]).source == 'approximate'
    assert resolve_context(C, key(20), [e]).technique_id == 1


def test_track_context_and_explicit_precedence():
    e = episode()
    assert resolve_context(replace(C, track_id=2), key(20), [e]).state == 'unrecorded'
    assert resolve_context(replace(C, height='1'), key(20), [e]).state == 'unrecorded'
    inferred = resolve_context(C, key(20), [e])
    mixed = Attribution('mixed', source='session')
    explicit = Attribution('technique', 9, source='recorded')
    assert resolve_use(inferred, session=mixed) == mixed
    assert resolve_use(inferred, explicit, mixed) == explicit


def test_ambiguity_rejected_and_specific_context_wins():
    with pytest.raises(ValueError, match='Ambiguous'):
        resolve_context(C, key(20), [episode(), episode(2)])
    assert resolve_context(C, key(20), [episode(), episode(2, constrain_position=True)]).technique_id == 2


def test_catalog_families_do_not_infer_armstand_or_transfer():
    for code, expected in [('103', '1'), ('5132', '51'), ('5233', '52'), ('5333', '53'), ('5433', '54'), ('612', None), ('6243', None)]:
        assert family(code) == expected
    assert resolve_context(replace(C, code='5132'), key(20), [episode(scope='1')]).state == 'unrecorded'


def test_recorded_union_excludes_gap_and_recurrence_but_keeps_conflicts():
    a = episode(end=key(20))
    b = episode(2, start=key(30), end=key(40))
    assert recorded_side(key(35), 1, a, b) == 0
    assert recorded_side(key(25), 1, a, b) is None
    assert recorded_side(key(45), 1, a, b) is None
    assert recorded_side(key(35), 3, a, b) is None
    with pytest.raises(ValueError, match='Repeated identity'):
        recorded_side(key(15), 1, a, replace(b, technique_id=1))


def test_comparison_rejects_every_incompatible_dimension():
    for field, value in [('diver_id', 2), ('track_id', 2), ('code', '104'), ('apparatus', 'platform'), ('height', '5'), ('position', 'C'), ('sync', True)]:
        with pytest.raises(ValueError, match='identical'):
            validate_pair(C, replace(C, **{field: value}))


def test_same_time_immutable_id_is_half_open_tiebreaker():
    t = datetime(2026, 1, 1)
    a = episode(start=OrderKey(t, 1), end=OrderKey(t, 2))
    b = episode(2, start=OrderKey(t, 2))
    assert resolve_context(C, OrderKey(t, 1), [a, b]).technique_id == 1
    assert resolve_context(C, OrderKey(t, 2), [a, b]).technique_id == 2
