"""Periodic scheduler that renders fresh stats into the static landing page."""
import logging
import os
import re

from pathlib import Path

from telegram.ext import ContextTypes

from database.queries import get_landing_stats
from utils.sentry import sentry_transaction, sentry_drop_transaction


LANDING_INDEX = Path(__file__).resolve().parent.parent / "landing" / "index.html"

# Match the text content between an opening tag carrying data-stat="<key>" and its
# closing "</". Idempotent: the rendered value still contains the marker, so the
# next tick can replace it again.
_MARKER_PATTERN = re.compile(r'(data-stat="([a-z\-]+)"[^>]*>)([^<]*)(</)')


def _round_down(value: int, step: int) -> int:
    return (value // step) * step


def _render_values(stats: dict[str, int]) -> dict[str, str]:
    completed = stats["completed"]
    failed = stats["failed"]
    seconds = stats["duration_seconds"]

    hours = _round_down(seconds // 3600, 100)

    denominator = completed + failed
    rate = 100.0 * completed / denominator if denominator else 100.0

    return {
        "hours": f"{hours}+",
        "success-rate": f"{rate:.1f}%",
    }


@sentry_transaction(name="landing.refresh_stats", op="task.refresh")
async def refresh_landing_stats(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-render the three data-stat markers in landing/index.html."""
    try:
        stats = get_landing_stats()
    except Exception:
        logging.exception("Failed to read landing stats from DB")
        sentry_drop_transaction()
        return

    values = _render_values(stats)

    try:
        html = LANDING_INDEX.read_text(encoding="utf-8")
    except FileNotFoundError:
        logging.warning("Landing index not found at %s; skipping refresh", LANDING_INDEX)
        sentry_drop_transaction()
        return

    def _replace(match: re.Match) -> str:
        opener, key, _old, closer = match.groups()
        new_value = values.get(key)
        if new_value is None:
            return match.group(0)
        return f"{opener}{new_value}{closer}"

    new_html = _MARKER_PATTERN.sub(_replace, html)

    if new_html == html:
        sentry_drop_transaction()
        return

    tmp_path = LANDING_INDEX.with_name(".index.html.tmp")
    tmp_path.write_text(new_html, encoding="utf-8")
    os.replace(tmp_path, LANDING_INDEX)
