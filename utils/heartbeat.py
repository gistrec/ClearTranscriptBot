"""In-process liveness heartbeats for critical scheduler loops.

Each critical scheduler calls beat() at the top of every tick. The healthcheck
endpoint reads these to tell "process alive" apart from "loop actually running",
catching the silent-failure case where polling stalls while the process (and a
naive healthcheck) stays up. monotonic() so it is immune to wall-clock changes.
"""
import time


# Loop name -> max seconds allowed between ticks before it counts as stale.
# Ticks run far more often than these (transcription/refinement @1s, payments
# @10s); thresholds are loose enough to tolerate a slow tick under load without
# flapping, yet still catch a real stall within a minute or two.
THRESHOLDS = {
    "transcription": 60,
    "refinement": 60,
    "payments": 120,
}

_started_at = time.monotonic()
_last_beat: dict[str, float] = {}


def beat(name: str) -> None:
    """Record that *name*'s loop just ran a tick."""
    _last_beat[name] = time.monotonic()


def overdue() -> dict[str, float]:
    """Return {name: age_seconds} for loops that are overdue (or never started).

    A loop that has not beaten yet is only reported once the process has been up
    longer than its threshold, so a fresh start doesn't trigger a false alarm.
    """
    now = time.monotonic()
    result: dict[str, float] = {}
    for name, threshold in THRESHOLDS.items():
        last = _last_beat.get(name)
        age = now - last if last is not None else now - _started_at
        if age > threshold:
            result[name] = age
    return result
