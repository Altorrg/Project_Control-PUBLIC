from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Any


def latest_round_date(rounds: Iterable[Mapping[str, Any]]) -> date | None:
    values: list[date] = []
    for row in rounds:
        for key in ("sent_date", "received_date"):
            value = row.get(key)
            if isinstance(value, date):
                values.append(value)
            elif value:
                values.append(date.fromisoformat(str(value)[:10]))
    return max(values) if values else None


def weighted_progress(assignments: Iterable[Mapping[str, Any]]) -> dict[str, Decimal | int]:
    total = Decimal("0")
    closed = Decimal("0")
    open_count = 0
    closed_count = 0
    for row in assignments:
        weight = Decimal(str(row.get("weight") or 0))
        total += weight
        if bool(row.get("is_closed")):
            closed += weight
            closed_count += 1
        else:
            open_count += 1
    percent = (closed / total * Decimal("100")) if total else Decimal("0")
    return {
        "total_weight": total,
        "closed_weight": closed,
        "progress_percent": percent.quantize(Decimal("0.01")),
        "open_count": open_count,
        "closed_count": closed_count,
    }

