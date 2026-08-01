#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verify QTimer probe markers using journald monotonic timestamps."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

MARKER = "HCPM_QTIMER_PROBE "
RUN = "qtimer-probe-v1"
TIMESTAMP = re.compile(r"^\[\s*(\d+(?:\.\d+)?)\]")
EXPECTED_SAMPLES = 20
STALL_SLACK_MS = 5000.0


def parse_markers(path: Path) -> list[dict]:
    markers: list[dict] = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        if MARKER not in line:
            continue
        timestamp_match = TIMESTAMP.match(line)
        if not timestamp_match:
            raise ValueError(f"line {line_number}: missing short-monotonic timestamp")
        payload = json.loads(line.split(MARKER, 1)[1])
        if payload.get("run") != RUN:
            continue
        payload["_monotonicSeconds"] = float(timestamp_match.group(1))
        markers.append(payload)
    return markers


def matching(markers: list[dict], **fields: object) -> list[dict]:
    return [
        marker
        for marker in markers
        if all(marker.get(key) == value for key, value in fields.items())
    ]


def interval_result(markers: list[dict], interval_ms: int) -> dict:
    durations: list[float] = []
    missing = 0
    duplicates = 0
    for sample in range(EXPECTED_SAMPLES):
        event_id = f"{interval_ms}-{sample}"
        starts = matching(
            markers,
            test="interval",
            id=event_id,
            event="start",
        )
        timeouts = matching(
            markers,
            test="interval",
            id=event_id,
            event="timeout",
        )
        if len(starts) != 1 or not timeouts:
            missing += 1
            continue
        duplicates += max(0, len(timeouts) - 1)
        durations.append(
            (timeouts[0]["_monotonicSeconds"] - starts[0]["_monotonicSeconds"])
            * 1000.0
        )

    early = sum(duration < interval_ms for duration in durations)
    late = sum(
        duration > interval_ms + STALL_SLACK_MS for duration in durations
    )
    return {
        "requestedMs": interval_ms,
        "expected": EXPECTED_SAMPLES,
        "measured": len(durations),
        "minimumMs": min(durations) if durations else None,
        "maximumMs": max(durations) if durations else None,
        "meanMs": statistics.fmean(durations) if durations else None,
        "medianMs": statistics.median(durations) if durations else None,
        "earlyCallbacks": early,
        "missingCallbacks": missing,
        "duplicateCallbacks": duplicates,
        "overFiveSecondsLate": late,
        "pass": (
            len(durations) == EXPECTED_SAMPLES
            and early == 0
            and missing == 0
            and duplicates == 0
        ),
    }


def elapsed_ms(first: dict, second: dict) -> float:
    return (
        second["_monotonicSeconds"] - first["_monotonicSeconds"]
    ) * 1000.0


def verify(markers: list[dict], cleanup_confirmed: bool) -> dict:
    fatal = matching(markers, test="suite", event="fatal")
    configured = matching(markers, event="configured")
    precise = bool(configured) and all(
        marker.get("timerType") == 0 for marker in configured
    )
    single_shot_readback = bool(configured) and all(
        marker.get("singleShot") is True for marker in configured
    )

    cancel_stopped = matching(
        markers, test="cancel", id="target", event="stopped"
    )
    cancel_observed = matching(
        markers, test="cancel", id="target", event="observed"
    )
    cancel_unexpected = matching(
        markers, test="cancel", id="target", event="unexpected-timeout"
    )
    cancel_pass = (
        len(cancel_stopped) == 1
        and cancel_stopped[0].get("active") is False
        and len(cancel_observed) == 1
        and cancel_observed[0].get("timeoutCount") == 0
        and not cancel_unexpected
    )

    independent_pass = all(
        len(matching(markers, test="independent", id=event_id, event="timeout"))
        == 1
        for event_id in ("DP-1:TopLeft", "HDMI-A-1:TopRight")
    )

    restart_markers = matching(
        markers, test="restart", id="target", event="restart"
    )
    restart_timeouts = matching(
        markers, test="restart", id="target", event="timeout"
    )
    restart_elapsed = (
        elapsed_ms(restart_markers[0], restart_timeouts[0])
        if len(restart_markers) == 1 and len(restart_timeouts) == 1
        else None
    )
    restart_pass = restart_elapsed is not None and restart_elapsed >= 350

    zero_timeouts = matching(
        markers, test="zero", id="target", event="timeout"
    )
    ready = matching(markers, test="suite", event="ready-for-unload")
    unload_unexpected = matching(
        markers, test="unload", id="target", event="unexpected-timeout"
    )
    cleanup_pass = cleanup_confirmed and len(ready) == 1 and not unload_unexpected

    intervals = {
        "350": interval_result(markers, 350),
        "500": interval_result(markers, 500),
    }
    capabilities = {
        "constructor": (
            len(matching(markers, test="constructor", event="available")) == 1
            and not fatal
        ),
        "timeoutConnection": all(result["measured"] for result in intervals.values()),
        "singleShot": (
            single_shot_readback
            and all(result["duplicateCallbacks"] == 0 for result in intervals.values())
        ),
        "preciseTimerReadback": precise,
        "stopCancel": cancel_pass,
        "independentTimers": independent_pass,
        "restartResetsDeadline": restart_pass,
        "zeroIntervalFiresOnce": len(zero_timeouts) == 1,
        "cleanupUnload": cleanup_pass,
    }
    passed = (
        not fatal
        and all(capabilities.values())
        and all(result["pass"] for result in intervals.values())
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "markerCount": len(markers),
        "fatalMarkers": fatal,
        "capabilities": capabilities,
        "restartElapsedFromRestartMs": restart_elapsed,
        "intervals": intervals,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path)
    parser.add_argument(
        "--cleanup-confirmed",
        action="store_true",
        help="unloadScript succeeded and the log includes the post-unload wait",
    )
    args = parser.parse_args()

    try:
        result = verify(parse_markers(args.log), args.cleanup_confirmed)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
