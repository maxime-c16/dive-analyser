"""Link meet result rows to app accounts, only when the match is unambiguous.

Sheets print "First LAST" (or "LAST First") and a club truncated to ~30
characters; accounts mostly carry a first name only. A row is linked when:

1. its club is a club of the app (sheet club = the club's name, a truncated
   prefix of it, or its short name), and only that club's active members
   are candidates;
2. names match in tiers, strongest first: full name on the account, full name
   on a diver the account owns (or its aliases), first name on the account,
   first name on an owned diver. The first tier with any candidate decides,
   and it must hold exactly one account;
3. no other person on the sheet resolves to the same account (two "Louis" of
   the club on one sheet link neither).

Synchro pairs are never linked. A wrong link is worse than none: everything
uncertain stays plain text.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.calendar import Club, ClubMembership
from app.models.diver import Diver, DiverAlias
from app.models.user_auth import AppUser, UserDiverAccess

MIN_CLUB_PREFIX = 8


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\s\-’']+", " ", text).strip().casefold()


def split_name(name: str) -> tuple[str, str]:
    """(given, surname), folded. Surname = the all-caps words, or the part
    before a comma ("LAST, First")."""
    if "," in name:
        last, _, first = name.partition(",")
        return fold(first), fold(last)
    words = name.split()
    surname = [w for w in words if w.isupper() and any(c.isalpha() for c in w)]
    given = [w for w in words if w not in surname]
    if not surname or not given:
        return fold(name), ""
    return fold(" ".join(given)), fold(" ".join(surname))


def _club_ids(db: Session, sheet_clubs: Iterable[str]) -> dict[str, int]:
    clubs = db.query(Club.id, Club.name, Club.short_name).filter(Club.archived_at.is_(None)).limit(500).all()
    out = {}
    for sheet in sheet_clubs:
        f = fold(sheet)
        hits = {cid for cid, name, short in clubs
                if (len(f) >= MIN_CLUB_PREFIX and fold(name).startswith(f)) or (short and f == fold(short))}
        if len(hits) == 1:
            out[sheet] = hits.pop()
    return out


def _names_by_user(db: Session, club_ids: set[int]) -> dict[int, tuple[set[str], set[str]]]:
    """user_id -> (account names, owned diver names + aliases), folded."""
    rows = db.query(AppUser.id, AppUser.display_name, ClubMembership.club_id).join(
        ClubMembership, ClubMembership.user_id == AppUser.id).filter(
        ClubMembership.club_id.in_(club_ids), ClubMembership.status == "active", ClubMembership.ended_at.is_(None),
        AppUser.is_active.is_(True)).limit(5000).all()
    names: dict[int, tuple[set[str], set[str]]] = {}
    clubs_of: dict[int, set[int]] = defaultdict(set)
    for uid, display, cid in rows:
        names.setdefault(uid, ({fold(display)}, set()))
        clubs_of[uid].add(cid)
    if names:
        owned = db.query(UserDiverAccess.user_id, Diver.id, Diver.display_name).join(
            Diver, Diver.id == UserDiverAccess.diver_id).filter(
            UserDiverAccess.user_id.in_(names), UserDiverAccess.access_kind == "OWNER").all()
        diver_users = defaultdict(set)
        for uid, did, dname in owned:
            names[uid][1].add(fold(dname))
            diver_users[did].add(uid)
        aliases = db.query(DiverAlias.diver_id, DiverAlias.alias).filter(
            DiverAlias.diver_id.in_(diver_users)).limit(5000) if diver_users else []
        for did, alias in aliases:
            for uid in diver_users[did]:
                names[uid][1].add(fold(alias))
    return {uid: (n, clubs_of[uid]) for uid, n in names.items()}


def _candidates(full: set[str], given: str, users: dict, club_id: int) -> list[int]:
    pool = {uid: n for uid, (n, clubs) in users.items() if club_id in clubs}
    tiers = (
        lambda own, divers: bool(own & full),
        lambda own, divers: bool(divers & full),
        lambda own, divers: given in own,
        lambda own, divers: given in divers,
    )
    for test in tiers:
        hits = [uid for uid, (own, divers) in pool.items() if test(own, divers)]
        if hits:
            return hits
    return []


def auto_links(db: Session, entries: list) -> dict[int, int]:
    """Map index in `entries` (objects with diver_name, birth_year, club_name)
    to the one account it unambiguously belongs to."""
    clubs = _club_ids(db, {e.club_name for e in entries if " / " not in e.diver_name})
    if not clubs:
        return {}
    users = _names_by_user(db, set(clubs.values()))
    person_user: dict[tuple, Optional[int]] = {}
    person_of: dict[int, tuple] = {}
    for i, e in enumerate(entries):
        if " / " in e.diver_name or e.club_name not in clubs:
            continue
        given, surname = split_name(e.diver_name)
        person = (given, surname, e.birth_year, clubs[e.club_name])
        person_of[i] = person
        if person in person_user:
            continue
        full = {f"{given} {surname}".strip(), f"{surname} {given}".strip()}
        hits = _candidates(full, given, users, clubs[e.club_name])
        person_user[person] = hits[0] if len(hits) == 1 else None
    claimed = defaultdict(set)
    for person, uid in person_user.items():
        if uid is not None:
            claimed[uid].add(person)
    return {i: person_user[p] for i, p in person_of.items()
            if person_user[p] is not None and len(claimed[person_user[p]]) == 1}
