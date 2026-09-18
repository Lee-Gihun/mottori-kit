#!/usr/bin/env python3
"""Regression pins for ``tools/transcribe.py``: the deterministic half of the listening recipe
(``filter_hallucinations``) and the instance-owned prompt file (``prompt_for``).

Measured 2026-09-18 on a restaurant recording: Whisper repeated one sentence dozens of times ("I'm not a
friend." x14) and invented subtitle credits ("한글자막 by ...", Korean subtitles by). The filter drops such
segments and reports their time as noise spans, so an unreadable span is handed to a person instead of being
invented. The other half of the recipe (ffmpeg filter chain and decoding thresholds) is not deterministic and
is validated by listening, not here.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from testlib import run_test

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import transcribe as T  # noqa: E402


def seg(start, end, text, logprob=-0.3, no_speech=0.1, ratio=1.4):
    return {"start": start, "end": end, "text": text, "avg_logprob": logprob,
            "no_speech_prob": no_speech, "compression_ratio": ratio}


def texts(segments):
    return [s["text"] for s in segments]


def test_repeated_lines_become_one_noise_span():
    segs = ([seg(0, 2, "안녕하세요")]
            + [seg(2 + i * 2, 4 + i * 2, "I'm not a friend.") for i in range(6)]
            + [seg(20, 23, "그래서 왔어요")])
    spans, kept = T.filter_hallucinations(segs)
    assert texts(kept) == ["안녕하세요", "그래서 왔어요"], texts(kept)
    assert spans == [(2, 14)], spans


def test_low_confidence_and_watermark_segments_are_dropped():
    segs = [seg(0, 3, "한글자막 by 한효정"), seg(3, 6, "진짜 대화", logprob=-0.4),
            seg(6, 9, "웅얼웅얼", logprob=-2.0), seg(9, 12, "노이즈", no_speech=0.9),
            seg(12, 15, "반복반복반복", ratio=3.1)]
    spans, kept = T.filter_hallucinations(segs)
    assert texts(kept) == ["진짜 대화"], texts(kept)
    # A drop shorter than NOISE_SPAN_MIN_SEC is not a span on its own; adjacent drops merge into one.
    assert spans == [(6, 15)], spans


def test_clean_transcript_is_untouched():
    segs = [seg(i * 3, i * 3 + 3, f"sentence {i}") for i in range(10)]
    spans, kept = T.filter_hallucinations(segs)
    assert len(kept) == 10 and spans == [], (spans, len(kept))


def test_consecutive_duplicate_collapses_without_a_span():
    segs = [seg(0, 2, "네"), seg(2, 4, "네"), seg(4, 6, "그렇죠")]
    spans, kept = T.filter_hallucinations(segs)
    assert texts(kept) == ["네", "그렇죠"], texts(kept)
    assert spans == [], spans


def test_english_watermark_is_dropped_too():
    segs = [seg(0, 4, "Thanks for watching, subscribe to the channel"), seg(4, 8, "we shipped the experiment")]
    spans, kept = T.filter_hallucinations(segs)
    assert texts(kept) == ["we shipped the experiment"], texts(kept)
    assert spans == [], spans


def test_prompt_file_overrides_generic_default():
    """Domain vocabulary is instance data: the prompt file wins per language, an empty value or a missing or
    unreadable file leaves the generic engine default in place."""
    with tempfile.TemporaryDirectory(prefix="transcribe-prompts-") as tmp:
        path = os.path.join(tmp, "prompts.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"ko": "한국어 대화. 팀 이름, 제품 이름.", "en": ""}, handle)
        assert T.prompt_for("ko", path) == "한국어 대화. 팀 이름, 제품 이름."
        assert T.prompt_for("en", path) == T.PROMPTS["en"]
        assert T.prompt_for("ko", os.path.join(tmp, "missing.json")) == T.PROMPTS["ko"]
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        assert T.prompt_for("en", path) == T.PROMPTS["en"]
    # The engine default carries no proper nouns: every English word after the first is lowercase.
    assert T.PROMPTS["ko"] and T.PROMPTS["en"]
    tail = T.PROMPTS["en"].split()[1:]
    assert tail and all(word == word.lower() for word in tail), T.PROMPTS["en"]


TESTS = [test_repeated_lines_become_one_noise_span,
         test_low_confidence_and_watermark_segments_are_dropped,
         test_clean_transcript_is_untouched,
         test_consecutive_duplicate_collapses_without_a_span,
         test_english_watermark_is_dropped_too,
         test_prompt_file_overrides_generic_default]


if __name__ == "__main__":
    for test in TESTS:
        run_test(test, __file__)
        print("PASS", test.__name__)
    print(f"transcribe filter: {len(TESTS)}/{len(TESTS)} passed")
