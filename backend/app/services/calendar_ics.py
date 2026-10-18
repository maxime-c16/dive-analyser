"""One-occurrence RFC 5545 snapshot, never a subscription or scheduling message.

UTC instants avoid floating-time/DST ambiguity and the need for VTIMEZONE.
The original IANA zone remains informational. No roster, resources or media.
"""
from datetime import timezone


def text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(c for c in value if c == "\n" or ord(c) >= 32 and ord(c) != 127)
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line: str) -> str:
    """Fold at 75 UTF-8 octets, including the continuation space."""
    parts, current = [], ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += char
    return "\r\n".join(parts + [current])


def utc(value) -> str:
    return value.replace(tzinfo=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def render(event, occurrence) -> str:
    cancelled = event.status == "cancelled" or occurrence.status == "cancelled"
    modified = max(event.updated_at, occurrence.updated_at)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dive Analyser//Calendar//EN", "CALSCALE:GREGORIAN",
             "BEGIN:VEVENT", f"UID:calendar-occurrence-{occurrence.id}@dive-analyser",
             f"DTSTAMP:{utc(modified)}", f"LAST-MODIFIED:{utc(modified)}",
             # Both counters only increase; max() would miss independent changes.
             f"SEQUENCE:{event.version + occurrence.version - 2}",
             f"STATUS:{'CANCELLED' if cancelled else 'TENTATIVE' if event.status == 'draft' else 'CONFIRMED'}",
             f"SUMMARY:{text(event.title)}", f"X-DIVE-ANALYSER-TIMEZONE:{text(event.timezone)}"]
    if occurrence.is_all_day:
        lines += [f"DTSTART;VALUE=DATE:{occurrence.start_date:%Y%m%d}",
                  f"DTEND;VALUE=DATE:{occurrence.end_date:%Y%m%d}"]
    else:
        lines += [f"DTSTART:{utc(occurrence.starts_at)}", f"DTEND:{utc(occurrence.ends_at)}"]
    description = event.description or ""
    description += "\nTimezone: " + event.timezone + "\nDownloaded snapshot; does not update automatically."
    lines.append(f"DESCRIPTION:{text(description)}")
    location = ", ".join(v for v in (occurrence.venue_name or event.venue_name, event.venue_address) if v)
    if location:
        lines.append(f"LOCATION:{text(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
