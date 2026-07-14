"""Tests for the Scribe challenger fallback helpers (providers.scribe).

Thresholds and behaviours are locked against the July 2026 25-file prod A/B:
quiet recordings recover speech, silence stays honestly empty, good primary
results never trigger the challenger.
"""
import os

os.environ.setdefault("REPLICATE_API_TOKEN", "test")

from decimal import Decimal

import pytest

from providers.replicate import get_text
from providers.scribe import (
    REASON_EMPTY,
    REASON_GARBAGE,
    REASON_LOW_COVERAGE,
    REASON_QUIET,
    build_payload,
    challenger_wins,
    cost_in_rub,
    coverage,
    meaningful_chars,
    should_try,
    words_to_segments,
)


def _word(text, start, end, speaker=None, type_="word"):
    return {"text": text, "start": start, "end": end, "type": type_, "speaker_id": speaker}


def _spacing():
    return {"text": " ", "type": "spacing"}


def _payload(segments):
    return {"status": "succeeded", "output": {"segments": segments}}


def _seg(start, end, text="речь"):
    return {"start": start, "end": end, "text": text}


class TestCost:
    def test_rounds_minutes_up(self):
        assert cost_in_rub(61) == Decimal("0.59")

    def test_sub_minute_bills_one_minute(self):
        assert cost_in_rub(1) == Decimal("0.29")

    def test_zero_duration_bills_one_minute(self):
        assert cost_in_rub(0) == Decimal("0.29")


class TestMeaningfulChars:
    def test_counts_speech(self):
        assert meaningful_chars("Привет, мир") == 10

    def test_strips_audio_event_tags(self):
        assert meaningful_chars("[музыка] [всхлип]") == 0

    def test_tag_inside_speech(self):
        assert meaningful_chars("Привет [смех] мир") == meaningful_chars("Привет мир")

    def test_empty_and_none(self):
        assert meaningful_chars(None) == 0
        assert meaningful_chars("") == 0


class TestChallengerWins:
    def test_needs_min_floor(self):
        assert not challenger_wins("", "а" * 29)
        assert challenger_wins("", "а" * 30)

    def test_needs_ratio_margin(self):
        assert not challenger_wins("а" * 100, "б" * 129)
        assert challenger_wins("а" * 100, "б" * 130)

    def test_event_tags_do_not_win(self):
        assert not challenger_wins("а" * 100, "[музыка]" * 50)


class TestWordsToSegments:
    def test_joins_words_with_spacing(self):
        segments = words_to_segments(
            {"words": [_word("Привет,", 0.0, 0.5), _spacing(), _word("мир", 0.6, 1.0)]}
        )
        assert segments == [{"start": 0.0, "end": 1.0, "text": "Привет, мир"}]

    def test_splits_on_long_pause(self):
        segments = words_to_segments(
            {"words": [_word("Раз", 0.0, 0.5), _word("Два", 2.0, 2.5)]}
        )
        assert [s["text"] for s in segments] == ["Раз", "Два"]

    def test_splits_on_speaker_change(self):
        segments = words_to_segments(
            {"words": [_word("Раз", 0.0, 0.5, speaker="A"), _word("Два", 0.6, 1.0, speaker="B")]}
        )
        assert [s["text"] for s in segments] == ["Раз", "Два"]

    def test_audio_event_flows_into_text(self):
        segments = words_to_segments(
            {"words": [_word("Раз", 0.0, 0.5), _spacing(), _word("[смех]", 0.6, 1.0, type_="audio_event")]}
        )
        assert segments[0]["text"] == "Раз [смех]"

    def test_skips_words_without_timestamps(self):
        segments = words_to_segments(
            {"words": [_word("Раз", 0.0, 0.5), _word("сирота", None, None)]}
        )
        assert [s["text"] for s in segments] == ["Раз"]

    def test_empty_output(self):
        assert words_to_segments({}) == []
        assert words_to_segments({"words": []}) == []


class TestBuildPayload:
    def test_compatible_with_replicate_get_text(self):
        info = {
            "status": "succeeded",
            "output": {
                "language_code": "rus",
                "words": [_word("Привет,", 0.0, 0.5), _spacing(), _word("мир", 0.6, 1.0)],
            },
            "predict_time": 2.5,
        }
        payload = build_payload("pred-id", info)
        assert get_text(payload) == "Привет, мир"
        assert payload["output"]["detected_language"] == "rus"


class TestCoverage:
    def test_full_coverage(self):
        assert coverage(_payload([_seg(0, 100)]), 100) == 1.0

    def test_sparse_coverage(self):
        assert coverage(_payload([_seg(0, 10)]), 100) == pytest.approx(0.1)

    def test_zero_duration(self):
        assert coverage(_payload([]), 0) == 1.0


def _try(**overrides):
    args = dict(
        provider="replicate",
        duration_seconds=300,
        mean_volume_db=-20.0,
        payload=_payload([_seg(0, 290)]),
        text="а" * 3000,
        wrong_language=False,
        hallucinated=False,
    )
    args.update(overrides)
    return should_try(**args)


class TestShouldTry:
    def test_good_result_never_triggers(self):
        assert _try() is None

    def test_quiet_recording_triggers(self):
        assert _try(mean_volume_db=-45.0) == REASON_QUIET

    def test_volume_at_sensitive_vad_band_does_not_trigger(self):
        assert _try(mean_volume_db=-37.0) is None

    def test_empty_text_triggers(self):
        assert _try(text="") == REASON_EMPTY

    def test_hallucinated_triggers(self):
        assert _try(hallucinated=True) == REASON_GARBAGE

    def test_low_coverage_triggers(self):
        assert _try(payload=_payload([_seg(0, 30)])) == REASON_LOW_COVERAGE

    def test_short_clip_exempt_from_coverage(self):
        assert _try(duration_seconds=30, payload=_payload([_seg(0, 3)])) is None

    def test_wrong_language_excluded(self):
        assert _try(wrong_language=True, mean_volume_db=-45.0) is None

    def test_speechkit_excluded(self):
        assert _try(provider="speechkit", mean_volume_db=-45.0) is None

    def test_over_duration_cap_excluded(self):
        assert _try(duration_seconds=9 * 3600, mean_volume_db=-45.0) is None

    def test_kill_switch(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_FALLBACK_ENABLED", "0")
        assert _try(mean_volume_db=-45.0) is None
