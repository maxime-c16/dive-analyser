from datetime import datetime
from decimal import Decimal

from app.models.dive import Dive
from app.models.session import Session as SessionModel
from app.models.diver import Diver, DiverAlias
from app.services.diver_identity import canonicalize_name, resolve_diver


def test_canonical_name_collapses_case_and_whitespace():
    assert canonicalize_name("  Maxime   Cauchy ") == "maxime cauchy"


def test_exact_canonical_resolution_does_not_duplicate(test_db):
    first = resolve_diver(test_db, "Paul")
    second = resolve_diver(test_db, "  PAUL  ")
    assert first.id == second.id


def test_alias_resolves_explicitly_without_automatic_fuzzy_merge(test_db):
    diver = resolve_diver(test_db, "Paul Martin")
    test_db.add(DiverAlias(diver_id=diver.id, alias="Paulo", canonical_alias="paulo", source="test"))
    test_db.commit()
    assert resolve_diver(test_db, "PAULO").id == diver.id
    assert resolve_diver(test_db, "Paul M").id != diver.id


def test_blank_name_resolves_configured_primary_diver(test_db):
    primary = resolve_diver(test_db, None)
    assert primary.is_primary_user is True
    assert resolve_diver(test_db, " ").id == primary.id


# --- DIVER_ID_19_HARDENING_V2: inactive-diver resolution hardening ---

def test_inactive_diver_is_not_resolved_by_canonical_name(test_db):
    diver = resolve_diver(test_db, "RIP")
    diver.active = False
    test_db.commit()
    assert resolve_diver(test_db, "RIP", create=False) is None


def test_inactive_diver_is_not_resolved_via_alias(test_db):
    diver = resolve_diver(test_db, "RIP")
    test_db.add(DiverAlias(diver_id=diver.id, alias="Rippy", canonical_alias="rippy", source="test"))
    diver.active = False
    test_db.commit()
    assert resolve_diver(test_db, "Rippy", create=False) is None
    assert resolve_diver(test_db, "RIP", create=False) is None


def test_inactive_diver_input_does_not_reattach_phantom_row(test_db):
    """Regression: historical RIP input must never silently rebind to the
    retired orphan row (mirror of production diver_id=19)."""
    phantom = resolve_diver(test_db, "RIP")
    phantom_id = phantom.id
    phantom.active = False
    test_db.commit()
    # historical-style rebinding attempt: resolver must not return diver 19...
    resolved = resolve_diver(test_db, "RIP", create=False)
    assert resolved is None
    # ...and creation must not resurrect it under a new id nor crash on the
    # unique canonical_name constraint: retired-name input stays unbound.
    assert resolve_diver(test_db, "RIP", create=True) is None


def test_active_allcaps_athletes_still_resolve(test_db):
    for name in ("TOM", "PAUL", "FANNY", "SARA", "MAT"):
        d = resolve_diver(test_db, name, create=True)
        assert d.active is True
        assert d.id == resolve_diver(test_db, name, create=False).id


def test_existing_dives_of_retired_diver_remain_inspectable(test_db):
    diver = resolve_diver(test_db, "RIP")
    session = SessionModel(date=datetime(2024, 1, 1).date())
    test_db.add(session)
    test_db.flush()
    dive = Dive(
        session_id=session.id, diver_id=diver.id, dive_code="101B", height="1m",
        performance="G", performance_numeric=3.5, dive_datetime=datetime(2024, 1, 1, 12, 0, 0), official_dd=Decimal("1.4"), notes="historical row",
    )
    test_db.add(dive)
    diver.active = False
    test_db.commit()
    stored = test_db.get(Dive, dive.id)
    assert stored.diver_id == diver.id  # data untouched, still inspectable
