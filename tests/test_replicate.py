"""Characterization tests for pure helpers in providers.replicate.

Lock the hallucination heuristic against the real-audio cases it was tuned on:
genuine foreign speech must pass, looping/low-confidence garbage must flag.
"""
import os

os.environ.setdefault("REPLICATE_API_TOKEN", "test")

from providers.replicate import get_text, looks_like_hallucination


def _payload(segments):
    return {"output": {"detected_language": "xx", "segments": segments}}


def test_get_text_joins_segments():
    payload = _payload([{"text": " Привет "}, {"text": "мир"}, {"text": ""}])
    assert get_text(payload) == "Привет\nмир"


def test_real_foreign_speech_passes():
    # 15783 tr / 15303 hi / 15570 it: genuine foreign, avg_logprob near zero.
    payload = _payload([
        {"text": "Erdemli Sakarya ilinin", "avg_logprob": -0.019},
        {"text": "Sapanca ilcesine bagli", "avg_logprob": -0.029},
    ])
    assert looks_like_hallucination(payload) is False


def test_low_logprob_flags():
    # 16066 tr (-0.575) and 15949 fi (-0.933): low-confidence garbage.
    payload = _payload([
        {"text": "Allah'a emanet olun", "avg_logprob": -0.36},
        {"text": "Sen islerin iyi mi", "avg_logprob": -0.79},
    ])
    assert looks_like_hallucination(payload) is True


def test_repetition_flags():
    # 16047 kk: the same long phrase looped many times.
    loop = {"text": "Сізден bring down дүген", "avg_logprob": -0.05}
    assert looks_like_hallucination(_payload([loop, loop, loop])) is True


def test_repeated_short_phrase_does_not_flag():
    ok = {"text": "да", "avg_logprob": -0.05}
    assert looks_like_hallucination(_payload([ok, ok, ok, ok])) is False


def test_empty_output_does_not_flag():
    assert looks_like_hallucination({"output": None}) is False
