"""Pure normalizers for Zabbix payloads returned through the Grafana datasource."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any

ERROR_DETAIL_MAX_CHARS = 300
ZABBIX_UNRESOLVED_EVENT_ID = "0"

_SEVERITY_LABELS = {
    0: "not_classified",
    1: "information",
    2: "warning",
    3: "average",
    4: "high",
    5: "disaster",
}
_FIELD_TYPE_TIME = "time"
_FIELD_TYPE_NUMBER = "number"
_AVERAGE_PRECISION = 6


def error_detail(body: str) -> str:
    """Bounded error text from a Grafana/Zabbix error body (JSON or plain)."""
    text = body.strip()
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
    return text[:ERROR_DETAIL_MAX_CHARS]


def to_int(value: Any) -> int | None:
    """Zabbix returns numeric fields as strings; convert, or ``None`` when unparseable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def epoch_seconds_to_iso(value: Any) -> str | None:
    """ISO 8601 UTC string for a Zabbix epoch-seconds field; ``None`` for unset (0)."""
    seconds = to_int(value)
    if not seconds or seconds < 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def epoch_ms_to_iso(value: Any) -> str | None:
    """ISO 8601 UTC string for a Grafana epoch-milliseconds timestamp."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def severity_label(value: Any) -> str:
    """Name for a Zabbix severity level (0-5)."""
    level = to_int(value)
    return _SEVERITY_LABELS.get(level, "unknown") if level is not None else "unknown"


def is_resolved(problem: dict[str, Any]) -> bool:
    """True once the problem has a recovery event (``r_eventid`` is ``"0"`` while open)."""
    recovery_event = str(problem.get("r_eventid") or ZABBIX_UNRESOLVED_EVENT_ID)
    return recovery_event != ZABBIX_UNRESOLVED_EVENT_ID


def last_activity_seconds(problem: dict[str, Any]) -> int:
    """Latest of the problem's start and recovery times, in epoch seconds."""
    return max(to_int(problem.get("clock")) or 0, to_int(problem.get("r_clock")) or 0)


def normalize_problem(
    problem: dict[str, Any], trigger_hosts: dict[str, list[str]]
) -> dict[str, Any]:
    """Map a raw ``problem.get`` row to the tool-facing shape, attaching trigger hosts."""
    started = to_int(problem.get("clock"))
    resolved_at = to_int(problem.get("r_clock"))
    resolved = is_resolved(problem)
    duration: int | None = None
    if started and resolved and resolved_at and resolved_at >= started:
        duration = resolved_at - started
    tags = problem.get("tags")
    trigger_id = str(problem.get("objectid") or "")
    return {
        "event_id": str(problem.get("eventid") or ""),
        "trigger_id": trigger_id,
        "name": str(problem.get("name") or ""),
        "severity": to_int(problem.get("severity")),
        "severity_label": severity_label(problem.get("severity")),
        "status": "resolved" if resolved else "problem",
        "acknowledged": str(problem.get("acknowledged") or "0") == "1",
        "suppressed": str(problem.get("suppressed") or "0") == "1",
        "started_at": epoch_seconds_to_iso(problem.get("clock")),
        "resolved_at": epoch_seconds_to_iso(problem.get("r_clock")) if resolved else None,
        "duration_seconds": duration,
        "hosts": trigger_hosts.get(trigger_id, []),
        "operational_data": str(problem.get("opdata") or ""),
        "tags": [
            {"tag": str(tag.get("tag", "")), "value": str(tag.get("value", ""))}
            for tag in (tags if isinstance(tags, list) else [])
            if isinstance(tag, dict)
        ],
    }


def extract_query_error(payload: dict[str, Any], ref_id: str) -> str | None:
    """Error text for a failed ``/api/ds/query`` result entry, or ``None`` when it succeeded.

    Grafana answers HTTP 200 with the failure nested under ``results.<refId>``.
    """
    results = payload.get("results")
    entry = results.get(ref_id) if isinstance(results, dict) else None
    if not isinstance(entry, dict):
        return "Zabbix query returned no result for the requested query."
    error = entry.get("error")
    if isinstance(error, str) and error.strip():
        return error.strip()[:ERROR_DETAIL_MAX_CHARS]
    status = to_int(entry.get("status"))
    if status is not None and status >= 400:
        return f"Zabbix query failed with status {status}."
    return None


def _display_name(frame: dict[str, Any], field: dict[str, Any]) -> str:
    config = field.get("config")
    if isinstance(config, dict):
        for key in ("displayNameFromDS", "displayName"):
            value = config.get(key)
            if isinstance(value, str) and value:
                return value
    schema = frame.get("schema")
    frame_name = schema.get("name") if isinstance(schema, dict) else None
    if isinstance(frame_name, str) and frame_name:
        return frame_name
    return str(field.get("name") or "")


def _sample_points(points: list[tuple[Any, float]], max_points: int) -> list[list[Any]]:
    """Evenly thin ``points`` to at most ``max_points``, always keeping the latest."""
    if len(points) <= max_points:
        sampled = points
    else:
        step = math.ceil(len(points) / max_points)
        sampled = points[::step]
        if sampled[-1] is not points[-1]:
            sampled = [*sampled[: max_points - 1], points[-1]]
    return [[epoch_ms_to_iso(timestamp), value] for timestamp, value in sampled]


def _series_from_field(
    frame: dict[str, Any],
    field: dict[str, Any],
    times: list[Any],
    values: list[Any],
    max_points: int,
) -> dict[str, Any]:
    points = [
        (timestamp, float(value))
        for timestamp, value in zip(times, values, strict=False)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    labels = field.get("labels")
    config = field.get("config")
    unit = config.get("unit") if isinstance(config, dict) else None
    if not points:
        return {
            "name": _display_name(frame, field),
            "labels": labels if isinstance(labels, dict) else {},
            "unit": unit,
            "count": 0,
            "points": [],
        }
    numbers = [value for _timestamp, value in points]
    return {
        "name": _display_name(frame, field),
        "labels": labels if isinstance(labels, dict) else {},
        "unit": unit,
        "count": len(numbers),
        "first": numbers[0],
        "last": numbers[-1],
        "min": min(numbers),
        "max": max(numbers),
        "avg": round(sum(numbers) / len(numbers), _AVERAGE_PRECISION),
        "points": _sample_points(points, max_points),
    }


def frames_to_series(
    frames: list[Any], *, max_series: int, max_points: int
) -> tuple[list[dict[str, Any]], int]:
    """Summarize Grafana data frames into per-item series with stats and sampled points.

    Returns ``(series, total_series)``; ``series`` is capped at ``max_series`` while
    ``total_series`` counts every numeric series the query produced.
    """
    series: list[dict[str, Any]] = []
    total = 0
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        schema = frame.get("schema")
        data = frame.get("data")
        fields = schema.get("fields") if isinstance(schema, dict) else None
        columns = data.get("values") if isinstance(data, dict) else None
        if not isinstance(fields, list) or not isinstance(columns, list):
            continue
        time_index = next(
            (
                index
                for index, field in enumerate(fields)
                if isinstance(field, dict) and field.get("type") == _FIELD_TYPE_TIME
            ),
            None,
        )
        if time_index is None or time_index >= len(columns):
            continue
        times = columns[time_index]
        for index, field in enumerate(fields):
            is_numeric = isinstance(field, dict) and field.get("type") == _FIELD_TYPE_NUMBER
            if index == time_index or not is_numeric or index >= len(columns):
                continue
            total += 1
            if len(series) >= max_series:
                continue
            item = _series_from_field(frame, field, times, columns[index], max_points)
            series.append(item)
    return series, total
