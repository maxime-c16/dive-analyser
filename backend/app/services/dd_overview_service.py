"""Live, traceable degree-of-difficulty overview for the primary diver."""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.dive import Dive
from app.services.diver_identity import get_primary_diver
from app.services.world_aquatics_dd import OfficialDDUndefined, REFERENCE_ID, REFERENCE_LABEL, calculate_official_dd


def _round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


class DDOverviewService:
    """Builds a live view without trusting stale persisted DD values."""

    def __init__(self, db: Session):
        self.db = db

    def overview(self, *, diver_id: int | None = None, scope: str = "self") -> dict:
        statement = select(Dive).options(selectinload(Dive.diver)).where(
            Dive.is_lineup.is_(False), Dive.dive_code.isnot(None), Dive.dive_datetime.isnot(None)
        )
        if diver_id is not None:
            statement = statement.where(Dive.diver_id == diver_id)
        elif scope != "all":
            primary = get_primary_diver(self.db)
            statement = statement.where(
                or_(Dive.diver_id == primary.id, (Dive.diver_id.is_(None) & Dive.person_name.is_(None)))
            )
        dives = list(self.db.execute(statement.order_by(Dive.dive_datetime.asc(), Dive.id.asc())).scalars())

        rows: list[dict] = []
        undefined: Counter[str] = Counter()
        mismatches = 0
        for dive in dives:
            try:
                result = calculate_official_dd(dive.dive_code, dive.height)
            except OfficialDDUndefined as error:
                undefined[str(error)] += 1
                continue
            value = float(result.dd)
            stored = float(dive.official_dd) if dive.official_dd is not None else None
            if stored is not None and abs(stored - value) >= 0.05:
                mismatches += 1
            rows.append({
                "attempt_id": dive.id,
                "dive_code": dive.dive_code,
                "height": result.height,
                "dive_datetime": dive.dive_datetime,
                "dd_value": value,
                "stored_dd": stored,
                "is_sync": bool(dive.is_sync),
                "diver": {"id": dive.diver.id, "display_name": dive.diver.display_name} if dive.diver else None,
                "components": {key: float(component) for key, component in result.components.items()},
                "reference_id": result.reference_id,
            })

        monthly: dict[str, list[float]] = defaultdict(list)
        by_height: dict[str, list[float]] = defaultdict(list)
        by_code: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for row in rows:
            monthly[row["dive_datetime"].strftime("%Y-%m")].append(row["dd_value"])
            by_height[row["height"]].append(row["dd_value"])
            by_code[(row["dive_code"], row["height"])].append(row)

        timeline = [
            {
                "month": month,
                "attempt_count": len(values),
                "median_dd": _round(float(median(values))),
                "max_dd": _round(max(values)),
                "min_dd": _round(min(values)),
            }
            for month, values in sorted(monthly.items())
        ]
        inventory = []
        for (code, height), attempts in sorted(by_code.items(), key=lambda item: (-max(row["dd_value"] for row in item[1]), item[0])):
            latest = attempts[-1]
            inventory.append({
                "dive_code": code,
                "height": height,
                "dd_value": latest["dd_value"],
                "attempt_count": len(attempts),
                "first_attempt_at": attempts[0]["dive_datetime"],
                "last_attempt_at": latest["dive_datetime"],
            })

        values = [row["dd_value"] for row in rows]
        return {
            "reference": {
                "id": REFERENCE_ID,
                "label": REFERENCE_LABEL,
                "method": "component_formula",
                "status": "versioned_reference",
            },
            "scope": "all" if scope == "all" and diver_id is None else "selected_diver" if diver_id is not None else "self",
            "summary": {
                "attempt_count": len(dives),
                "defined_attempt_count": len(rows),
                "undefined_attempt_count": len(dives) - len(rows),
                "unique_dive_count": len(by_code),
                "median_dd": _round(float(median(values))) if values else None,
                "max_dd": _round(max(values)) if values else None,
                "min_dd": _round(min(values)) if values else None,
                "legacy_mismatch_count": mismatches,
            },
            "timeline": timeline,
            "height_breakdown": [
                {"height": height, "attempt_count": len(values), "median_dd": _round(float(median(values))), "max_dd": _round(max(values))}
                for height, values in sorted(by_height.items())
            ],
            "inventory": inventory,
            "recent_attempts": list(reversed(rows[-12:])),
            "undefined_reasons": [{"reason": reason, "attempt_count": count} for reason, count in undefined.most_common()],
        }
