"""Parse DiveRecorder "Résultats détaillés" PDFs (the FFN meet result sheets).

The PDF has a real text layer; pypdf extracts one line per printed row:

    N° HauteurCoef J1 J2 J3 J4 J5 J6 J7 Cumul Points Points Pen   <- table header
    Elite - Messieurs - 3m                                         <- event title
    Paul EXEMPLE (1967) -- Club Plongeon de Quelque Part 3          <- diver, place last
    304C 3 2,1 4,0 3,5 2,5 3,5 3,0   10,0 21,00 176,55 4double ... <- dive (+ penalty code)

Layout facts, from DiveRecorder's own report definitions (repDetailNormal /
repDetailSynchro .fr3), not guessed from one sample:

- Dive row: code, height, DD, judges, judges' sum (1 decimal), points and
  running total (2 decimals), then optionally the place after that round (a
  bare integer) and the penalty code 1–4, which is printed against the dive
  name. Individual panels are 3/5/7 judges (unused columns blank); synchro
  prints J1–J7 before the sum and J8–J11 after the running total. So the
  row is read by number format, not by column position.
- Diver line: "<name> -- <club>[ (guest)][ (disqualified|withdrew|knocked
  out)][  #licence]" then the place, blank when unranked. The birth year is
  part of the name in some name formats. Synchro pairs print two such lines.
- An event title is repeated after each page break; the same title continues
  the event unless the places restart (a second round under the same name).

Official numbers are stored exactly as printed (docs/SCORING.md §4). The
parser only checks the sheet's own arithmetic and reports mismatches as
warnings; it never recomputes or re-ranks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Optional

MAX_PAGES = 60
MAX_EVENTS = 100
MAX_ENTRIES = 2000
MAX_DIVES = 20000
MAX_WARNINGS = 50
MAX_JUDGES = 11

# A number is followed by whitespace or the end: a digit glued to text is a penalty code.
_TOKEN = r"\d+(?:,\d+)?(?=\s|$)"
_HEADER = re.compile(r"^N°\s+Hauteur")
_DIVE = re.compile(rf"^(?P<code>\d{{2,4}}[A-D])\s+(?P<nums>{_TOKEN}(?:\s+{_TOKEN})+)(?P<rest>.*)$")
_PENALTY = re.compile(r"^ ?(?P<pen>[1-4])(?=\D|$)")
_DIVER = re.compile(r"^(?P<name>.+?)\s+--\s+(?P<club>.*?)(?:\s+#\S+)?(?:\s+(?P<place>\d{1,3}))?$")
_YEAR = re.compile(r"\s+\((?P<year>(?:19|20)\d{2})\)$")
_ONE_DECIMAL = re.compile(r"^\d+,\d$")
_TWO_DECIMALS = re.compile(r"^\d+,\d\d$")
_NOISE = re.compile(r"^(Codes des pénalités|Penalty codes|https?://|Résultats détaillés$|\d+\.\d+\.\d+\.\d+$)")
# Suffixes DiveRecorder appends to the club (English and French builds).
_STATUS = {"disqualified": "disqualified", "disqualifié": "disqualified", "withdrew": "withdrawn",
           "abandon": "withdrawn", "knocked out": "knocked_out", "assommé": "knocked_out"}
_GUEST = {"guest", "invité"}
_SUFFIX = re.compile(r"\s*\((?P<word>[^()]+)\)$")
_MONTHS = {m: i for i, m in enumerate(("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                                       "septembre", "octobre", "novembre", "décembre"), 1)}
_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE)
_CENT = Decimal("0.01")


class MeetPdfError(ValueError):
    """The file is not a readable DiveRecorder result sheet. `code` is stable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ParsedDive:
    dive_code: str
    height: Decimal
    dd: Decimal
    judge_half_steps: list[int]
    cumul: Decimal
    points: Decimal
    running_total: Decimal
    penalty: Optional[int]


@dataclass
class ParsedEntry:
    rank: Optional[int]
    diver_name: str
    birth_year: Optional[int]
    club_name: str
    status: Optional[str] = None  # disqualified | withdrawn | knocked_out
    guest: bool = False
    dives: list[ParsedDive] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return self.dives[-1].running_total if self.dives else Decimal("0")


@dataclass
class ParsedEvent:
    title: str
    board: str
    entries: list[ParsedEntry] = field(default_factory=list)


@dataclass
class ParsedMeet:
    meet_date: Optional[date]
    events: list[ParsedEvent]
    warnings: list[str]

    @property
    def entry_count(self) -> int:
        return sum(len(e.entries) for e in self.events)

    @property
    def dive_count(self) -> int:
        return sum(len(en.dives) for e in self.events for en in e.entries)


def _dec(token: str) -> Decimal:
    return Decimal(token.replace(",", "."))


def _board(title: str) -> str:
    return title.rsplit(" - ", 1)[-1].strip()[:16]


def _diver(line: str) -> Optional[tuple[ParsedEntry, bool]]:
    """The entry and whether the line printed a place (synchro line A always does)."""
    m = _DIVER.match(line)
    if not m:
        return None
    name, club = m.group("name").strip(), m.group("club").strip()
    status, guest = None, False
    while (s := _SUFFIX.search(club)) and (s.group("word").lower() in _STATUS or s.group("word").lower() in _GUEST):
        word = s.group("word").lower()
        if word in _GUEST:
            guest = True
        else:
            status = _STATUS[word]
        club = club[:s.start()].rstrip()
    year = _YEAR.search(name)
    if year:
        name = name[:year.start()]
    place = int(m.group("place")) if m.group("place") else 0
    return ParsedEntry(rank=place or None, diver_name=name[:120],
                       birth_year=int(year.group("year")) if year else None, club_name=club[:120],
                       status=status, guest=guest), m.group("place") is not None


def _dive(m: re.Match) -> Optional[ParsedDive]:
    tokens = m.group("nums").split()
    # Points and running total are the first two 2-decimal numbers after the DD.
    k = next((i for i in range(3, len(tokens) - 1) if _TWO_DECIMALS.match(tokens[i])), None)
    if k is None or not _TWO_DECIMALS.match(tokens[k + 1]) or not _ONE_DECIMAL.match(tokens[k - 1]):
        return None
    marks = tokens[2:k - 1] + [t for t in tokens[k + 2:] if "," in t]  # synchro J8–J11 follow the total
    if not marks or len(marks) > MAX_JUDGES or not all(_ONE_DECIMAL.match(t) for t in marks):
        return None
    judges = [_dec(t) for t in marks]
    if any(j > 10 or (j * 2) % 1 for j in judges):
        return None
    pen = _PENALTY.match(m.group("rest"))
    return ParsedDive(dive_code=m.group("code"), height=_dec(tokens[0]), dd=_dec(tokens[1]),
                      judge_half_steps=[int(j * 2) for j in judges], cumul=_dec(tokens[k - 1]),
                      points=_dec(tokens[k]), running_total=_dec(tokens[k + 1]),
                      penalty=int(pen.group("pen")) if pen else None)


def pdf_text(raw: bytes) -> str:
    """Text layer of a PDF, page by page. Bounded by MAX_PAGES."""
    if not raw.startswith(b"%PDF-"):
        raise MeetPdfError("not_pdf", "The file is not a PDF")
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(BytesIO(raw))
        if len(reader.pages) > MAX_PAGES:
            raise MeetPdfError("too_many_pages", f"At most {MAX_PAGES} pages")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except MeetPdfError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation, RecursionError) as exc:
        raise MeetPdfError("unreadable_pdf", "The PDF could not be read") from exc


def parse_text(text: str) -> ParsedMeet:
    events: list[ParsedEvent] = []
    warnings: list[str] = []
    meet_date: Optional[date] = None
    event: Optional[ParsedEvent] = None
    entry: Optional[ParsedEntry] = None
    expect_title = False
    continuing = False  # a repeated title after a page break
    entries = dives = 0
    pair_open = False  # last diver line printed a place and no dive followed yet

    def warn(msg: str) -> None:
        if len(warnings) < MAX_WARNINGS:
            warnings.append(msg)

    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or _NOISE.match(line):
            continue
        if _HEADER.match(line):
            expect_title = True
            continue
        if event is None and not expect_title:
            # Preamble: venue, meet name, date. Only the date is kept (sanity check).
            m = _DATE.search(line)
            if m and meet_date is None:
                try:
                    meet_date = date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
                except ValueError:
                    pass
            continue
        if expect_title:
            expect_title = False
            if event is not None and line == event.title:
                continuing = True
                continue
            if len(events) >= MAX_EVENTS:
                raise MeetPdfError("too_large", f"At most {MAX_EVENTS} events")
            event, entry, continuing, pair_open = ParsedEvent(title=line[:200], board=_board(line)), None, False, False
            events.append(event)
            continue
        m = _DIVE.match(line)
        if m:
            dive = _dive(m)
            if entry is None or dive is None:
                warn(f"Line {lineno}: dive row not understood, ignored")
                continue
            previous = entry.dives[-1].running_total if entry.dives else Decimal("0")
            label = f"{entry.diver_name}, {event.title}, dive {len(entry.dives) + 1}"
            # Synchro panels (>7 judges) weight the sum, so only individual rows check points.
            if len(dive.judge_half_steps) <= 7 and (dive.cumul * dive.dd).quantize(_CENT) != dive.points:
                warn(f"{label}: points {dive.points} differ from {dive.cumul} × {dive.dd}")
            if previous + dive.points != dive.running_total:
                warn(f"{label}: running total {dive.running_total} differs from {previous} + {dive.points}")
            dives += 1
            if dives > MAX_DIVES:
                raise MeetPdfError("too_large", f"At most {MAX_DIVES} dives")
            entry.dives.append(dive)
            pair_open = False
            continue
        found = _diver(line) if event is not None else None
        if found is not None:
            parsed, has_place = found
            if pair_open and not has_place and entry is not None and not entry.dives:
                # Second line of a synchro pair: same result, two divers.
                entry.diver_name = f"{entry.diver_name} / {parsed.diver_name}"[:120]
                if parsed.club_name != entry.club_name:
                    entry.club_name = f"{entry.club_name} / {parsed.club_name}"[:120]
                entry.birth_year = None
                entry.status = entry.status or parsed.status
                entry.guest = entry.guest or parsed.guest
                pair_open = False
                continue
            last = event.entries[-1].rank if event.entries else None
            if continuing and parsed.rank is not None and last is not None and parsed.rank <= last:
                # Same title, places restart: a separate round, not a page continuation.
                event = ParsedEvent(title=event.title, board=event.board)
                events.append(event)
            continuing = False
            entries += 1
            if entries > MAX_ENTRIES:
                raise MeetPdfError("too_large", f"At most {MAX_ENTRIES} results")
            entry = parsed
            event.entries.append(entry)
            pair_open = has_place
            continue
        if event is not None:
            warn(f"Line {lineno}: not recognised, ignored")

    events = [e for e in events if e.entries]
    if not events:
        raise MeetPdfError("no_results", "No DiveRecorder results were found in this PDF")
    return ParsedMeet(meet_date=meet_date, events=events, warnings=warnings)


def parse_pdf(raw: bytes) -> ParsedMeet:
    return parse_text(pdf_text(raw))
