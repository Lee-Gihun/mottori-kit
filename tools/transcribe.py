#!/usr/bin/env python3
"""녹음 파일 하나를 전사한다. 레시피 정본은 2026-07-26 재전사 노트.

기본 동작:
  1) 입력을 16k mono wav로 정규화 (highpass/lowpass/dynaudnorm)
  2) mlx_whisper large-v3-turbo로 전사 (환각 억제 파라미터 고정)
  3) 타임스탬프 텍스트 + srt + json 저장
  4) 5초 이상 세그먼트 공백을 스캔해 실제 무음인지 volumedetect로 판정
     (무음이 아니면 결손 후보 = 사람이 확인해야 하는 자리)

왜 4)가 있나: 7/23 zerry 전사에서 30.3초가 통째로 빠지고 그 자리를 "감사합니다"
환각이 메웠다. 그 결손을 화자의 침묵으로 오독한 분석이 나왔다. 결손은 조용히
지나가지 않게 계기로 잡는다.

사용:
  python3 tools/transcribe.py <audio> [--out DIR] [--lang ko] [--keep-wav]
"""
import argparse, json, os, re, subprocess, sys, time

FILTER = "highpass=f=80,lowpass=f=7500,dynaudnorm=f=150:g=15"
MODEL = "mlx-community/whisper-large-v3-turbo"
GAP_SEC = 5.0          # 이 이상 벌어지면 결손 후보로 검사
SILENCE_DB = -45.0     # mean_volume이 이보다 작으면 실제 무음으로 판정


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def to_wav(src, dst):
    r = run(["ffmpeg", "-y", "-i", src, "-af", FILTER, "-ac", "1", "-ar", "16000", dst])
    if r.returncode != 0 or not os.path.exists(dst):
        sys.exit(f"ffmpeg 실패:\n{r.stderr[-800:]}")


def transcribe(wav, lang):
    import mlx_whisper
    return mlx_whisper.transcribe(
        wav,
        path_or_hf_repo=MODEL,
        language=lang,
        condition_on_previous_text=False,
        temperature=(0.0, 0.2, 0.4, 0.6),
        no_speech_threshold=0.9,
        logprob_threshold=-3.0,
        compression_ratio_threshold=4.0,
        word_timestamps=False,
    )


def hhmmss(t, comma=False):
    h, m = int(t // 3600), int((t % 3600) // 60)
    s, ms = int(t % 60), int((t - int(t)) * 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def mean_db(wav, start, end):
    r = run(["ffmpeg", "-ss", f"{start}", "-to", f"{end}", "-i", wav,
             "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", r.stderr or "")
    return float(m.group(1)) if m else None


def scan_gaps(segs, wav):
    """세그먼트 사이 공백을 검사해 (시작, 끝, dB, 판정) 목록을 만든다."""
    out = []
    for a, b in zip(segs, segs[1:]):
        gap = b["start"] - a["end"]
        if gap < GAP_SEC:
            continue
        db = mean_db(wav, a["end"], b["start"])
        verdict = "무음" if (db is not None and db < SILENCE_DB) else "결손 후보"
        out.append((a["end"], b["start"], db, verdict))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--out", default=None, help="출력 디렉토리 (기본: 입력 파일 옆)")
    ap.add_argument("--lang", default="ko")
    ap.add_argument("--keep-wav", action="store_true")
    ap.add_argument("--no-diarize", action="store_true", help="화자 분리 생략")
    ap.add_argument("--speakers", type=int, default=0, help="화자 수를 안다면 고정 (권장)")
    a = ap.parse_args()

    src = os.path.abspath(a.audio)
    if not os.path.exists(src):
        sys.exit(f"파일 없음: {src}")
    stem = os.path.splitext(os.path.basename(src))[0]
    outdir = os.path.abspath(a.out) if a.out else os.path.dirname(src)
    os.makedirs(outdir, exist_ok=True)
    wav = os.path.join(outdir, f".{stem}.16k.wav")

    t0 = time.time()
    print(f"[1/4] 오디오 정규화: {os.path.basename(src)}", flush=True)
    to_wav(src, wav)

    print(f"[2/4] 전사 (mlx large-v3-turbo, lang={a.lang}) — 오디오 길이의 약 1/8 소요", flush=True)
    res = transcribe(wav, a.lang)
    segs = res.get("segments") or []

    print(f"[3/4] 저장 ({len(segs)} 세그먼트)", flush=True)
    base = os.path.join(outdir, stem)
    with open(base + "-timestamped.txt", "w") as f:
        for s in segs:
            f.write(f"[{hhmmss(s['start'])}] {s['text'].strip()}\n")
    with open(base + ".txt", "w") as f:
        f.write("\n".join(s["text"].strip() for s in segs) + "\n")
    with open(base + ".srt", "w") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{hhmmss(s['start'], True)} --> {hhmmss(s['end'], True)}\n"
                    f"{s['text'].strip()}\n\n")
    with open(base + ".json", "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    print("[4/5] 결손 스캔", flush=True)
    gaps = scan_gaps(segs, wav)
    real = [g for g in gaps if g[3] == "결손 후보"]
    with open(base + "-QA.md", "w") as f:
        f.write(f"# 전사 QA — {stem}\n\n")
        f.write(f"세그먼트 {len(segs)} · 글자수 {sum(len(s['text']) for s in segs):,} · "
                f"길이 {hhmmss(segs[-1]['end']) if segs else '0'}\n\n")
        if not gaps:
            f.write(f"{GAP_SEC}초 이상 공백 없음.\n")
        else:
            f.write(f"| 시작 | 끝 | 평균 dB | 판정 |\n|---|---|---|---|\n")
            for st, en, db, v in gaps:
                f.write(f"| {hhmmss(st)} | {hhmmss(en)} | {db if db is None else round(db,1)} | {v} |\n")
        if real:
            f.write(f"\n**결손 후보 {len(real)}건. 해당 구간을 직접 들어보고, 빠진 발화가 있으면 "
                    f"그 구간만 잘라 재전사할 것. 결손을 화자의 침묵으로 읽지 말 것 (7/26 교훈).**\n")
    if not a.no_diarize:
        print("[5/5] 화자 분리 [추정]", flush=True)
        r = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "diarize.py"),
                 wav, "--segments", base + ".json", "--out", base + ".spk.txt"]
                + (["--k", str(a.speakers)] if a.speakers else []))
        print("   " + ((r.stdout or r.stderr).strip().splitlines() or ["실패"])[-1])

    if not a.keep_wav:
        os.remove(wav)

    print(f"\n완료 ({time.time()-t0:.0f}초): {base}-timestamped.txt")
    if not a.no_diarize:
        print(f"화자: {base}.spk.txt (추정 — 인용 전 청취)")
    print(f"QA: {base}-QA.md — 공백 {len(gaps)}건 중 결손 후보 {len(real)}건")


if __name__ == "__main__":
    main()
