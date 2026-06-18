"""Characterization tests for pure helpers in providers.replicate.

Lock the hallucination heuristic against the real-audio cases it was tuned on:
genuine foreign speech must pass, looping/low-confidence garbage must flag.
"""
import os

os.environ.setdefault("REPLICATE_API_TOKEN", "test")

from providers.replicate import get_text, looks_like_hallucination
from utils.timecodes import extract_segments, is_phantom_segment


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


def test_get_text_drops_phantom_credit_tail():
    # ~250 real cases: a clean transcription with the hallucinated DimaTorzok
    # subtitle credit appended as the final segment (e.g. id 19193).
    payload = _payload([
        {"text": " Реальная речь пользователя"},
        {"text": " Субтитры сделал DimaTorzok"},
    ])
    assert get_text(payload) == "Реальная речь пользователя"


def test_get_text_drops_tv_subtitle_credit():
    payload = _payload([
        {"text": " Полезный текст"},
        {"text": " Редактор субтитров А.Синецкая Корректор А.Егорова"},
    ])
    assert get_text(payload) == "Полезный текст"


def test_get_text_phantom_only_becomes_empty():
    # id 18755: the whole output is the artifact -> empty text, so the
    # scheduler falls back to the honest "no speech" message.
    payload = _payload([{"text": " Субтитры создавал DimaTorzok"}])
    assert get_text(payload) == ""


def test_get_text_keeps_lookalike_phrases():
    # Conservative scope: benign phrases users may actually say must survive
    # (zero false positives on good transcriptions).
    payload = _payload([
        {"text": " Спасибо за просмотр"},
        {"text": " Продолжение следует..."},
    ])
    assert get_text(payload) == "Спасибо за просмотр\nПродолжение следует..."


def test_extract_segments_drops_phantom_credit():
    payload = {"output": {"segments": [
        {"start": 0.0, "end": 2.0, "text": "Реальная речь"},
        {"start": 2.0, "end": 4.0, "text": "Субтитры подготовил DimaTorzok"},
    ]}}
    assert [s["text"] for s in extract_segments(payload)] == ["Реальная речь"]


def test_is_phantom_segment_scope():
    assert is_phantom_segment("Субтитры перевёл DimaTorzok")
    assert is_phantom_segment("Редактор субтитров А.Синецкая")
    assert not is_phantom_segment("Спасибо за просмотр")
    assert not is_phantom_segment("Продолжение следует...")
