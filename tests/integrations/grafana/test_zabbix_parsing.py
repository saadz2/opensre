"""Unit tests for the Zabbix payload normalizers."""

from __future__ import annotations

from typing import Any

from integrations.grafana.zabbix_parsing import (
    error_detail,
    extract_query_error,
    frames_to_series,
    normalize_problem,
    severity_label,
)

_BASE_MS = 1_790_000_000_000


def _frame(values: list[Any], *, name: str = "web-01: CPU utilization") -> dict[str, Any]:
    """A Grafana wide data frame as the Zabbix plugin returns it for one item."""
    return {
        "schema": {
            "refId": "A",
            "name": name,
            "fields": [
                {"name": "Time", "type": "time", "typeInfo": {"frame": "time.Time"}},
                {
                    "name": "Value",
                    "type": "number",
                    "typeInfo": {"frame": "float64", "nullable": True},
                    "labels": {"host": "web-01"},
                    "config": {"displayNameFromDS": name, "unit": "percent"},
                },
            ],
        },
        "data": {"values": [[_BASE_MS + index * 60_000 for index in range(len(values))], values]},
    }


def test_frames_to_series_summarizes_stats_and_skips_null_samples() -> None:
    series, total = frames_to_series(
        [_frame([10.0, None, 90.0, 50.0])], max_series=5, max_points=10
    )

    assert total == 1
    assert series[0]["name"] == "web-01: CPU utilization"
    assert series[0]["labels"] == {"host": "web-01"}
    assert series[0]["unit"] == "percent"
    assert (series[0]["count"], series[0]["min"], series[0]["max"]) == (3, 10.0, 90.0)
    assert series[0]["first"] == 10.0
    assert series[0]["last"] == 50.0
    assert series[0]["avg"] == 50.0


def test_frames_to_series_caps_series_but_reports_the_full_total() -> None:
    frames = [_frame([float(index)], name=f"item-{index}") for index in range(4)]

    series, total = frames_to_series(frames, max_series=2, max_points=10)

    assert [item["name"] for item in series] == ["item-0", "item-1"]
    assert total == 4


def test_frames_to_series_downsamples_but_keeps_the_latest_point() -> None:
    series, _total = frames_to_series(
        [_frame([float(index) for index in range(100)])], max_series=1, max_points=10
    )

    points = series[0]["points"]
    assert len(points) <= 10
    assert points[-1][1] == 99.0
    assert series[0]["count"] == 100


def test_frames_to_series_ignores_frames_without_a_time_field() -> None:
    frame = _frame([1.0])
    frame["schema"]["fields"][0]["type"] = "string"

    assert frames_to_series([frame], max_series=5, max_points=10) == ([], 0)


def test_extract_query_error_reads_nested_result_error() -> None:
    payload = {"results": {"A": {"status": 400, "error": "Item not found"}}}

    assert extract_query_error(payload, "A") == "Item not found"


def test_extract_query_error_flags_a_missing_result_and_passes_a_good_one() -> None:
    assert extract_query_error({"results": {}}, "A") is not None
    assert extract_query_error({"results": {"A": {"status": 200, "frames": []}}}, "A") is None


def test_error_detail_prefers_json_message_and_bounds_length() -> None:
    assert error_detail('{"message": "no such item"}') == "no such item"
    assert len(error_detail("x" * 1000)) == 300


def test_normalize_problem_maps_active_and_resolved_rows() -> None:
    active = {
        "eventid": "9001",
        "objectid": "13491",
        "clock": "1790000000",
        "r_eventid": "0",
        "r_clock": "0",
        "name": "High CPU on web-01",
        "severity": "4",
        "acknowledged": "1",
        "suppressed": "0",
        "tags": [{"tag": "service", "value": "checkout"}],
    }
    resolved = {**active, "eventid": "9002", "r_eventid": "9003", "r_clock": "1790000300"}

    normalized_active = normalize_problem(active, {"13491": ["web-01"]})
    normalized_resolved = normalize_problem(resolved, {})

    assert normalized_active["status"] == "problem"
    assert normalized_active["severity_label"] == "high"
    assert normalized_active["acknowledged"] is True
    assert normalized_active["hosts"] == ["web-01"]
    assert normalized_active["resolved_at"] is None
    assert normalized_active["tags"] == [{"tag": "service", "value": "checkout"}]
    assert normalized_resolved["status"] == "resolved"
    assert normalized_resolved["duration_seconds"] == 300
    assert normalized_resolved["resolved_at"] is not None


def test_severity_label_handles_unknown_values() -> None:
    assert severity_label("5") == "disaster"
    assert severity_label("banana") == "unknown"
    assert severity_label(None) == "unknown"
