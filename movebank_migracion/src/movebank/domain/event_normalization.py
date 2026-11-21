"""Normalize Movebank CSV event rows before analysis."""

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from numbers import Integral, Real
from typing import Any

import numpy as np
from pydantic import ValidationError

from movebank.domain.missing_values import is_missing_value
from movebank.domain.models import Event


def events_for_analysis(
    rows: Iterable[dict[str, Any]], include_unknown_visibility: bool = False
) -> list[dict[str, Any]]:
    """Return visible events, optionally including events with unknown visibility."""
    return [
        row
        for row in rows
        if row.get("visible") is True or (include_unknown_visibility and row.get("visible") is None)
    ]


@dataclass(frozen=True)
class EventNormalizationResult:
    """Validated event records and counts for rows that could not be normalized."""

    events: list[dict[str, Any]]
    rejected_by_reason: dict[str, int]

    @property
    def unknown_visibility_events(self) -> list[dict[str, Any]]:
        """Return accepted records whose visibility is unknown."""
        return [event for event in self.events if event["visible"] is None]

    @property
    def accepted_count(self) -> int:
        return len(self.events)

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected_by_reason.values())

    @property
    def hidden_count(self) -> int:
        return sum(event["visible"] is False for event in self.events)

    @property
    def unknown_visibility_count(self) -> int:
        return sum(event["visible"] is None for event in self.events)

    def events_for_analysis(self, include_unknown_visibility: bool = False) -> list[dict[str, Any]]:
        """Return visible records, optionally including records of unknown visibility."""
        return events_for_analysis(self.events, include_unknown_visibility)


def _is_missing(value: object) -> bool:
    return is_missing_value(value)


def _normalize_visible(value: object) -> bool | None:
    if isinstance(value, str) and value.strip().casefold() in {"nan", "nat"}:
        raise ValueError("Unrecognized visibility value.")
    if isinstance(value, np.datetime64) and np.isnat(value):
        raise ValueError("Unrecognized visibility value.")
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    elif isinstance(value, Integral | Real):
        if value == 1:
            return True
        if value == 0:
            return False
    raise ValueError("Unrecognized visibility value.")


def _normalize_coordinate(value: object) -> float:
    if _is_missing(value) or isinstance(value, bool):
        raise ValueError("Missing coordinate.")
    try:
        if isinstance(value, str | int | float | Decimal):
            coordinate = float(value)
        elif isinstance(value, Real):
            coordinate = value.__float__()
        else:
            raise TypeError("Coordinate is not numeric.")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid coordinate.") from exc
    if not math.isfinite(coordinate):
        raise ValueError("Invalid coordinate.")
    return coordinate


def _validation_reason(error: ValidationError) -> str:
    fields = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
    if "timestamp" in fields:
        return "invalid_timestamp"
    if fields.intersection({"location_lat", "location_long"}):
        return "invalid_coordinates"
    return "invalid_event"


def normalize_events(rows: Iterable[Mapping[str, object]]) -> EventNormalizationResult:
    """Validate CSV-like event rows and report rejected rows by reason.

    Visibility accepts booleans, case-insensitive ``true``/``false`` strings,
    and numeric or string ``1``/``0`` values. Empty, null, and NaN visibility
    remains ``None``; unexpected non-empty values are rejected. Numeric
    coordinate strings are converted to floats, then checked by ``Event`` for
    geographic bounds. Event timestamps use the formats accepted by ``Event``.

    Rejected rows are counted once. Model-validation failures are classified
    with timestamp errors taking priority over coordinate errors, then other
    event errors. Unknown visibility remains ``None`` and is excluded from
    analysis by default; use ``EventNormalizationResult.events_for_analysis``
    to opt into including those records.
    """
    events: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()

    for row in rows:
        if not isinstance(row, Mapping):
            rejected["invalid_row"] += 1
            continue

        values = dict(row)
        try:
            values["visible"] = _normalize_visible(values.get("visible"))
        except ValueError:
            rejected["invalid_visible"] += 1
            continue

        missing_coordinate = False
        invalid_coordinate = False
        for field in ("location_lat", "location_long"):
            if field not in values or _is_missing(values[field]):
                missing_coordinate = True
                break
            try:
                values[field] = _normalize_coordinate(values[field])
            except ValueError:
                invalid_coordinate = True
                break

        if missing_coordinate:
            rejected["missing_coordinates"] += 1
            continue
        if invalid_coordinate:
            rejected["invalid_coordinates"] += 1
            continue

        try:
            event = Event.model_validate(values)
        except ValidationError as exc:
            rejected[_validation_reason(exc)] += 1
            continue
        if event.individual_id is None:
            rejected["invalid_event"] += 1
            continue
        events.append(event.model_dump(mode="json"))

    return EventNormalizationResult(events, dict(rejected))
