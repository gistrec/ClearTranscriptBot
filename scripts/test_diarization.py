#!/usr/bin/env python3
"""
Throwaway test harness for option C: standalone diarization + merge.

Runs WhisperX (transcription) and a standalone speaker-diarization model on the
SAME audio, then merges them by max temporal overlap — no re-transcription. The
point is to eyeball quality on a real (ideally Russian, multi-speaker) recording
and to measure predict_time so we can price the extra pass.

Usage:
    REPLICATE_API_TOKEN=r8_... python scripts/test_diarization.py \
        --audio "https://.../meeting.mp3"

    # compare diarizers / constrain speaker count (collectiveai only):
    ... --diarizer collectiveai --num-speakers 2
    ... --large            # force the WhisperX A40-large variant (>1h files)

If --audio is omitted, the model's English 2-speaker demo clip is used, which is
enough to validate the merge mechanics (but not Russian quality).
"""
import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import replicate
import requests

from utils.timecodes import extract_segments, _fmt_short

# Version-pinned models (WhisperX ids mirror providers/replicate.py).
WHISPERX_SMALL = "victor-upmeet/whisperx:655845d6190ef70573c669245f245892cd039df4b880a1e3a65852c09252f5cc"
WHISPERX_LARGE = "victor-upmeet/whisperx-a40-large:8aad2534a4f2a268a80ab781928cf4bc624b0bbed25afe4d789c70c5781c47b1"
DIARIZERS = {
    # fast (~14s/4min), autodetect speaker count, output is a URL to output.json
    "meronym": "meronym/speaker-diarization:64b78c82f74d78164b49178443c819445f5dca2c51c8ec374783d49382342119",
    # ~9x slower, inline JSON, supports num/min/max_speakers (pyannote 3.1)
    "collectiveai": "collectiveai-team/speaker-diarization-3:6e29843b8c1b751ec384ad96d3566af2392046465152fef3cc22ad701090b64c",
}

USD_TO_RUB = Decimal("80")  # project constant, not a spot rate
WHISPERX_RATE_USD_PER_SEC = Decimal("0.001400")  # A100 80GB (MODEL_SMALL)

DEMO_AUDIO = "https://pyannote-speaker-diarization.s3.eu-west-2.amazonaws.com/lex-levin-4min.mp3"


def run_and_wait(client, version, payload, label):
    """Create a prediction, poll to completion, return (output, predict_time)."""
    pred = client.predictions.create(version=version, input=payload)
    print(f"  [{label}] started {pred.id} ...", flush=True)
    while pred.status not in ("succeeded", "failed", "canceled"):
        time.sleep(3)
        pred = client.predictions.get(pred.id)
    if pred.status != "succeeded":
        raise RuntimeError(f"{label} {pred.status}: {getattr(pred, 'error', None)}")
    predict_time = (getattr(pred, "metrics", None) or {}).get("predict_time")
    print(f"  [{label}] done in {predict_time}s", flush=True)
    return pred.output, predict_time


def _to_seconds(value):
    """Accept float seconds or a clock string 'H:MM:SS.ffffff' (meronym emits these)."""
    if isinstance(value, (int, float)):
        return float(value)
    h, m, s = str(value).split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def fetch_turns(diarizer, raw_output):
    """Normalize either diarizer's output into [{speaker, start, end}] (floats)."""
    if diarizer == "meronym":
        data = requests.get(str(raw_output), timeout=30).json()
        raw_segments = data.get("segments", [])
    else:  # collectiveai returns inline {segments, speakers}
        raw_segments = (raw_output or {}).get("segments", [])

    turns = []
    for t in raw_segments:
        try:
            turns.append({
                "speaker": str(t["speaker"]),
                "start": _to_seconds(t["start"]),
                "end": _to_seconds(t.get("stop", t.get("end"))),  # models emit 'stop'
            })
        except (KeyError, TypeError, ValueError):
            continue
    return turns


def assign_speakers(segments, turns):
    """Attach a speaker to each {start,end,text} segment by max temporal overlap."""
    out = []
    for seg in segments:
        best_spk, best_overlap = None, 0.0
        for turn in turns:
            overlap = min(seg["end"], turn["end"]) - max(seg["start"], turn["start"])
            if overlap > best_overlap:
                best_overlap, best_spk = overlap, turn["speaker"]
        out.append({**seg, "speaker": best_spk})
    return out


def format_diarized_txt(segments):
    """Group consecutive same-speaker segments under a [Спикер N] header."""
    labels = {}
    lines, prev = [], None
    for seg in segments:
        spk = seg.get("speaker") or "?"
        if spk not in labels:
            labels[spk] = f"Спикер {len(labels) + 1}"
        if spk != prev:
            lines.append(f"\n[{labels[spk]}]")
            prev = spk
        lines.append(f"[{_fmt_short(seg['start'])}] {seg['text']}")
    return "\n".join(lines).strip()


def parse_args():
    p = argparse.ArgumentParser(description="Test standalone diarization + merge")
    p.add_argument("--audio", default=DEMO_AUDIO, help="Audio URL (public, fetchable by Replicate)")
    p.add_argument("--diarizer", default="meronym", choices=list(DIARIZERS))
    p.add_argument("--large", action="store_true", help="Use WhisperX A40-large (>1h audio)")
    p.add_argument("--num-speakers", type=int, default=None, help="collectiveai only")
    p.add_argument("--outdir", default="diar_test_output")
    return p.parse_args()


def main():
    args = parse_args()
    if not os.getenv("REPLICATE_API_TOKEN"):
        print("REPLICATE_API_TOKEN must be set")
        sys.exit(1)

    client = replicate.Client(api_token=os.environ["REPLICATE_API_TOKEN"])
    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)

    print(f"Audio:    {args.audio}")
    print(f"Diarizer: {args.diarizer}\n")

    whisper_version = WHISPERX_LARGE if args.large else WHISPERX_SMALL
    whisper_out, whisper_pt = run_and_wait(
        client, whisper_version,
        {"audio_file": args.audio, "language_detection_min_prob": 0.9, "language_detection_max_tries": 10},
        "whisperx",
    )

    diar_input = {"audio": args.audio}
    if args.diarizer == "collectiveai" and args.num_speakers:
        diar_input["num_speakers"] = args.num_speakers
    diar_out, diar_pt = run_and_wait(client, DIARIZERS[args.diarizer], diar_input, "diarize")

    segments = extract_segments({"output": whisper_out})
    turns = fetch_turns(args.diarizer, diar_out)
    diarized = assign_speakers(segments, turns)

    plain = "\n".join(f"[{_fmt_short(s['start'])}] {s['text']}" for s in segments)
    diarized_txt = format_diarized_txt(diarized)
    speaker_count = len({s["speaker"] for s in diarized if s["speaker"]})
    unmatched = sum(1 for s in diarized if not s["speaker"])

    (outdir / "plain.txt").write_text(plain, encoding="utf-8")
    (outdir / "diarized.txt").write_text(diarized_txt, encoding="utf-8")
    (outdir / "turns.json").write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"segments={len(segments)}  turns={len(turns)}  speakers={speaker_count}  unmatched={unmatched}")
    if whisper_pt:
        wx_rub = (Decimal(str(whisper_pt)) * WHISPERX_RATE_USD_PER_SEC * USD_TO_RUB).quantize(Decimal("0.01"))
        print(f"whisperx predict_time={whisper_pt}s  (~{wx_rub} ₽ at A100 rate)")
    print(f"diarize  predict_time={diar_pt}s  (verify {args.diarizer} hardware rate on replicate.com)")
    print("=" * 60)
    print("\n--- DIARIZED (first 60 lines) ---")
    print("\n".join(diarized_txt.splitlines()[:60]))
    print(f"\nFull output written to: {outdir}/")


if __name__ == "__main__":
    main()
