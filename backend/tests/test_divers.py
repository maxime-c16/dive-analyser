from app.models.diver import DiverAlias
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
