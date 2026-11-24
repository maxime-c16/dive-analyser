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

Administrators override this per person (`meet_person_links`, keyed by
`person_key`): tie to an account, or never link. Decisions apply to every
meet, past and future, and an account tied by an administrator to anyone
leaves the automatic pool everywhere.

`person_key` is the federation licence when the sheet prints one, otherwise
folded name + birth year (0 when not printed) + folded sheet club. Known
limits, kept on purpose: the same diver on a sheet without the year, or
after changing club, is a different person for decisions; the admin decides
again there. Namesakes in different clubs never share a decision.

Imports and administrator decisions serialize on one transaction lock
(`lock_links`) so a concurrent import cannot republish a link an
administrator just removed.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calendar import Club, ClubMembership
from app.models.diver import Diver, DiverAlias
from app.models.user_auth import AppUser, UserDiverAccess

# DiveRecorder truncates the club to ~30 characters; only a name that long can
# be a truncated prefix ("ASPTT Paris" must not match "ASPTT Paris Plongeon").
MIN_CLUB_PREFIX = 25
# Candidate sets are loaded whole. If one exceeds its cap, matching fails
# closed (no automatic link) instead of deciding from a truncated set, where a
# missing namesake would make an ambiguous name look unique.
MAX_CLUBS = 500
MAX_CANDIDATE_ROWS = 5000


class _Truncated(Exception):
    pass


def _bounded(query, cap: int) -> list:
    rows = query.limit(cap + 1).all()
    if len(rows) > cap:
        raise _Truncated
    return rows


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


def _club_ids(db: Session, sheet_clubs: Iterable[str], cache: Optional[dict] = None) -> dict[str, int]:
    cache = {} if cache is None else cache
    if "clubs" not in cache:
        cache["clubs"] = _bounded(db.query(Club.id, Club.name, Club.short_name).filter(Club.archived_at.is_(None)), MAX_CLUBS)
    clubs = cache["clubs"]
    out = {}
    for sheet in sheet_clubs:
        f = fold(sheet)
        # An exact name or short name wins over a truncated prefix ("Club X" vs "Club X Nord").
        hits = {cid for cid, name, short in clubs if f == fold(name) or (short and f == fold(short))}
        if not hits and len(sheet.strip()) >= MIN_CLUB_PREFIX:
            hits = {cid for cid, name, short in clubs if fold(name).startswith(f)}
        if len(hits) == 1:
            out[sheet] = hits.pop()
    return out


def _names_by_user(db: Session, club_ids: set[int]) -> dict[int, tuple[set[str], set[str]]]:
    """user_id -> (account names, owned diver names + aliases), folded."""
    rows = _bounded(db.query(AppUser.id, AppUser.display_name, ClubMembership.club_id).join(
        ClubMembership, ClubMembership.user_id == AppUser.id).filter(
        ClubMembership.club_id.in_(club_ids), ClubMembership.status == "active", ClubMembership.ended_at.is_(None),
        AppUser.is_active.is_(True)), MAX_CANDIDATE_ROWS)
    names: dict[int, tuple[set[str], set[str]]] = {}
    clubs_of: dict[int, set[int]] = defaultdict(set)
    for uid, display, cid in rows:
        names.setdefault(uid, ({fold(display)}, set()))
        clubs_of[uid].add(cid)
    if names:
        owned = _bounded(db.query(UserDiverAccess.user_id, Diver.id, Diver.display_name).join(
            Diver, Diver.id == UserDiverAccess.diver_id).filter(
            UserDiverAccess.user_id.in_(names), UserDiverAccess.access_kind == "OWNER"), MAX_CANDIDATE_ROWS)
        diver_users = defaultdict(set)
        for uid, did, dname in owned:
            names[uid][1].add(fold(dname))
            diver_users[did].add(uid)
        aliases = _bounded(db.query(DiverAlias.diver_id, DiverAlias.alias).filter(
            DiverAlias.diver_id.in_(diver_users)), MAX_CANDIDATE_ROWS) if diver_users else []
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


LINKS_LOCK_ID = 0x6D656574  # "meet"


def lock_links(db: Session) -> None:
    """Serialize imports and administrator link decisions (PostgreSQL)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LINKS_LOCK_ID})


def person_key(diver_name: str, birth_year: Optional[int], club_name: str = "",
               licence: Optional[str] = None) -> Optional[str]:
    """Stable identity of a sheet row across meets; None for synchro pairs."""
    if " / " in diver_name:
        return None
    if licence:
        return f"lic:{fold(licence)}"[:160]
    given, surname = split_name(diver_name)
    return f"{given} {surname}".strip()[:100] + f"|{birth_year or 0}|" + fold(club_name)[:50]


def key_of(entry) -> Optional[str]:
    """Stored rows carry their key; parsed rows compute it (licence included)."""
    stored = getattr(entry, "person_key", None)
    if stored:
        return stored
    return person_key(entry.diver_name, entry.birth_year, entry.club_name, getattr(entry, "licence", None))


def decisions(db: Session, keys: Iterable[str]) -> dict[str, Optional[int]]:
    """Administrator decisions for these people: key -> user_id (None = never link)."""
    from app.models.meet_results import MeetPersonLink
    keys = {k for k in keys if k}
    if not keys:
        return {}
    return dict(db.query(MeetPersonLink.person_key, MeetPersonLink.user_id).filter(
        MeetPersonLink.person_key.in_(keys)).all())


def resolve(db: Session, entries: list, cache: Optional[dict] = None,
            decided: Optional[dict] = None) -> dict[int, tuple[Optional[int], str]]:
    """Index in `entries` (one meet) -> (user_id, source) for every row that
    has a link decision: 'admin' rows (user_id may be None) win over 'auto'
    matches. `cache` shares candidate lookups across meets; `decided` lets a
    caller prefetch the decisions of several meets in one query."""
    keys = [key_of(e) for e in entries]
    if decided is None:
        decided = decisions(db, keys)
    out: dict[int, tuple[Optional[int], str]] = {i: (decided[k], "admin") for i, k in enumerate(keys) if k in decided}
    cache = {} if cache is None else cache
    rest = [i for i in range(len(entries)) if i not in out]
    auto = auto_links(db, [entries[i] for i in rest], cache=cache)
    out.update({rest[j]: (uid, "auto") for j, uid in auto.items()})
    return out


def _claimed(db: Session, user_ids: Iterable[int]) -> set[int]:
    """Candidates an administrator tied to anyone, on any sheet. Bounded by the
    candidate set, not by the number of decisions."""
    from app.models.meet_results import MeetPersonLink
    ids = list(user_ids)
    if not ids:
        return set()
    return {uid for (uid,) in db.query(MeetPersonLink.user_id).filter(MeetPersonLink.user_id.in_(ids)).distinct()}


def auto_links(db: Session, entries: list, cache: Optional[dict] = None) -> dict[int, int]:
    """Map index in `entries` (objects with diver_name, birth_year, club_name)
    to the one account it unambiguously belongs to. Accounts an administrator
    already tied to someone are never candidates."""
    cache = {} if cache is None else cache
    try:
        clubs = _club_ids(db, {e.club_name for e in entries if " / " not in e.diver_name}, cache)
        if not clubs:
            return {}
        club_set = frozenset(clubs.values())
        if club_set not in cache:
            pool = _names_by_user(db, set(club_set))
            claimed = _claimed(db, pool)
            cache[club_set] = {uid: v for uid, v in pool.items() if uid not in claimed}
        users = cache[club_set]
    except _Truncated:
        return {}
    person_user: dict[tuple, Optional[int]] = {}
    person_of: dict[int, tuple] = {}
    for i, e in enumerate(entries):
        if " / " in e.diver_name or e.club_name not in clubs:
            continue
        given, surname = split_name(e.diver_name)
        # Identity as everywhere else (licence first): two licences are two people.
        person = (key_of(e), clubs[e.club_name])
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
