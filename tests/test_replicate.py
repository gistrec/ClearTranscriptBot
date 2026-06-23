"""Characterization tests for pure helpers in providers.replicate.

Lock the hallucination heuristic against the real-audio cases it was tuned on:
genuine foreign speech must pass, looping/low-confidence garbage must flag.

NOTE / ПРИМЕЧАНИЕ: the production cases referenced below by transcription id
were surfaced and their content analysed by an automated AI assistant during
heuristic calibration. The operator did NOT manually read the underlying user
recordings or transcripts; only the AI inspected that content, and only to tune
the false-positive thresholds.
Реальные кейсы (по id транскрибаций) ниже отбирал и анализировал
ИИ-ассистент автоматически; владелец сервиса сами записи/расшифровки
пользователей лично не просматривал.
"""
import os

os.environ.setdefault("REPLICATE_API_TOKEN", "test")

from providers.replicate import detected_language, get_text, is_wrong_language, looks_like_hallucination
from utils.timecodes import extract_segments, is_phantom_segment


def _payload(segments):
    return {"output": {"detected_language": "xx", "segments": segments}}


def _payload_lang(lang, segments):
    return {"output": {"detected_language": lang, "segments": segments}}


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


def test_real_speech_low_confidence_passes():
    # id 20107: a genuine heartfelt toast, dragged to mean -0.41 only by honest
    # repetition of "Спасибо". Must deliver, not refund (zero FP on good speech).
    payload = _payload([
        {"text": " Ребята, просто фантастика. Спасибо. Спасибо. Спасибо.", "avg_logprob": -0.4595},
        {"text": " Сегодня был очень веселый день. Мы вас любим.", "avg_logprob": -0.3646},
    ])
    assert looks_like_hallucination(payload) is False


def test_minor_repeat_in_long_transcript_passes():
    # id 20108/20158: a 1h+ meeting/lecture where one phrase loops 3x must not
    # condemn the whole otherwise-confident transcript.
    good = [{"text": f"Осмысленная реплика участника номер {i}", "avg_logprob": -0.1} for i in range(60)]
    loop = [{"text": "Спасибо за внимание коллеги", "avg_logprob": -0.1}] * 3
    assert looks_like_hallucination(_payload(good + loop)) is False


def test_dominant_loop_flags():
    # id 20143: near-silent recording where "Продолжение следует..." is most of
    # the output — looping that dominates is still garbage.
    loop = {"text": "Продолжение следует...", "avg_logprob": -0.25}
    other = {"text": "ЗВОНОК В ДВЕРЬ, ничего полезного", "avg_logprob": -0.35}
    assert looks_like_hallucination(_payload([loop, loop, loop, loop, loop, other])) is True


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


def test_detected_language():
    assert detected_language(_payload_lang("ru", [])) == "ru"
    assert detected_language({"output": None}) is None
    assert detected_language({}) is None


def test_wrong_language_flags_misdetect_codes():
    # uk/nn/kk/ko/zh/es: validated as near-always a misdetection of Russian.
    for code in ("uk", "nn", "kk", "ko", "zh", "es"):
        payload = _payload_lang(code, [{"text": "какой-то текст"}])
        assert is_wrong_language(payload) is True, code


def test_wrong_language_flags_foreign_script():
    # "Все пришло в иероглифах" / "разшифровало в китайский" — id 16070, 18630.
    assert is_wrong_language(_payload_lang("ja", [{"text": "これは日本語のテキストです"}])) is True
    assert is_wrong_language(_payload_lang("ar", [{"text": "هذا نص باللغة العربية"}])) is True


def test_wrong_language_passes_russian():
    payload = _payload_lang("ru", [{"text": "Привет, это обычная русская речь"}])
    assert is_wrong_language(payload) is False


def test_wrong_language_passes_english():
    payload = _payload_lang("en", [{"text": "This is a normal English transcript"}])
    assert is_wrong_language(payload) is False


def test_wrong_language_passes_legit_latin_foreign():
    # Genuine de/fr/tr/it (avg rating ~5) are Latin script and not blacklisted:
    # forcing a retry on them would be a false positive on good transcriptions.
    payload = _payload_lang("de", [{"text": "Das ist ein deutscher Text"}])
    assert is_wrong_language(payload) is False


def test_wrong_language_ignores_stray_foreign_glyph():
    # A single quoted foreign word inside Russian must not trip the detector.
    payload = _payload_lang("ru", [{"text": "Он купил телефон модели 小米 в магазине сегодня"}])
    assert is_wrong_language(payload) is False


def test_wrong_language_empty_text():
    assert is_wrong_language(_payload_lang("ru", [])) is False
