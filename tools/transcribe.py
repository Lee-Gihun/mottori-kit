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
import argparse, json, os, re, stat, subprocess, sys, tempfile, time

FILTER = "highpass=f=80,lowpass=f=7500,dynaudnorm=f=150:g=15"
MODEL = "mlx-community/whisper-large-v3-turbo"
GAP_SEC = 5.0          # 이 이상 벌어지면 결손 후보로 검사
SILENCE_DB = -45.0     # mean_volume이 이보다 작으면 실제 무음으로 판정
DETECT_LANGUAGES = ("ko", "en")   # 이 밖의 표는 버린다
DETECT_WINDOW_SEC = 30.0          # whisper 판별 단위와 같은 길이
DETECT_POINTS = (0.2, 0.5, 0.8)   # 도입부 인사말에 끌려가지 않게 본문에서 뽑는다
DETECT_MIN_TEXT = 10              # 이보다 짧게 나온 구간은 무음으로 보고 버린다


def _regular_input(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("input is not a regular file")
    finally:
        os.close(fd)


def _plain_output_directory(path):
    parent = os.path.dirname(path)
    try:
        return all(
            stat.S_ISDIR(os.lstat(candidate).st_mode)
            for candidate in (parent, path)
        )
    except OSError:
        return False


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def to_wav(src, dst):
    src_fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(src_fd).st_mode):
            sys.exit("일반 오디오 파일이 아니다: " + src)
        r = run(
            ["ffmpeg", "-y", "-i", "/dev/fd/{}".format(src_fd), "-af", FILTER,
             "-ac", "1", "-ar", "16000", dst],
            pass_fds=(src_fd,),
        )
    finally:
        os.close(src_fd)
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        sys.exit(f"ffmpeg 실패:\n{r.stderr[-800:]}")


def _reserved_output(path):
    if not os.path.lexists(path):
        return
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        sys.exit("reserved output이 안전하지 않다: " + path)


def _atomic_text(path, text):
    _reserved_output(path)
    fd, tmp = tempfile.mkstemp(prefix=".transcribe.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        tmp = None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


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


def audio_duration(path):
    """초 단위 길이. 오디오로 열리지 않으면 0을 준다 (판별을 건너뛰는 신호)."""
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path])
    try:
        return max(0.0, float((r.stdout or "").strip()))
    except ValueError:
        return 0.0


def _window_wav(src, start, length, dst):
    r = run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
             "-i", src, "-ac", "1", "-ar", "16000", dst])
    return r.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0


def detect_language(src, fallback="ko"):
    """오디오 여러 구간을 자동판별해 다수결로 전사 언어를 정한다.

    왜 파일명이 아니라 오디오인가: 언어를 파일명에 적게 하는 건 기계가 할 수 있는
    판정을 사람에게 떠넘기는 것이고, 빠뜨리면 결손이 아니라 유창한 오출력으로
    나타나 결손 QA에 걸리지 않는다 (8/30 GenZ readout — 영어 48분을 ko로 걸 뻔했다).

    왜 한 구간이 아닌가: 영어 회의도 한국어 인사말로 열리고 그 반대도 흔하다.
    동률이면 판별하지 못한 것으로 보고 fallback을 쓴다.

    반환: (언어코드 또는 None, 표 목록). None은 "판별 실패"이지 "ko"가 아니다.
    """
    duration = audio_duration(src)
    if duration < DETECT_WINDOW_SEC / 2:
        return None, []

    span = min(DETECT_WINDOW_SEC, duration)
    if duration <= DETECT_WINDOW_SEC * 1.5:
        offsets = [0.0]
    else:
        offsets = [
            min(max(0.0, duration * point - span / 2), duration - span)
            for point in DETECT_POINTS
        ]

    import mlx_whisper

    votes = []
    for start in offsets:
        fd, win = tempfile.mkstemp(prefix=".detect-lang.", suffix=".wav")
        os.close(fd)
        try:
            if not _window_wav(src, start, span, win):
                continue
            res = mlx_whisper.transcribe(
                win,
                path_or_hf_repo=MODEL,
                language=None,
                condition_on_previous_text=False,
                temperature=0.0,
                word_timestamps=False,
            )
            if len((res.get("text") or "").strip()) < DETECT_MIN_TEXT:
                continue
            if res.get("language") in DETECT_LANGUAGES:
                votes.append(res["language"])
        except Exception:
            continue
        finally:
            try:
                os.unlink(win)
            except OSError:
                pass

    if not votes:
        return None, votes
    counts = {code: votes.count(code) for code in set(votes)}
    top = max(counts.values())
    winners = [code for code, n in counts.items() if n == top]
    return (winners[0] if len(winners) == 1 else None), votes


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
    ap.add_argument("--detect-language", action="store_true",
                    help="오디오에서 언어만 판별해 코드를 찍고 끝낸다 (반입 단계용)")
    ap.add_argument("--keep-wav", action="store_true")
    ap.add_argument("--no-diarize", action="store_true", help="화자 분리 생략")
    ap.add_argument("--speakers", type=int, default=0, help="화자 수를 안다면 고정 (권장)")
    a = ap.parse_args()

    src = os.path.abspath(a.audio)
    try:
        _regular_input(src)
    except OSError:
        sys.exit(f"파일 없음: {src}")

    if a.detect_language:
        code, votes = detect_language(src)
        print("표본 {}: {}".format(len(votes), ",".join(votes) or "없음"), file=sys.stderr)
        if not code:
            return 1
        print(code)
        return 0

    stem = os.path.splitext(os.path.basename(src))[0]
    outdir = os.path.abspath(a.out) if a.out else os.path.dirname(src)
    try:
        os.makedirs(outdir, mode=0o700, exist_ok=True)
    except OSError as exc:
        sys.exit("출력 디렉터리를 만들 수 없다: {} ({})".format(outdir, exc))
    if not _plain_output_directory(outdir):
        sys.exit("출력 경로가 일반 디렉터리가 아니다: " + outdir)
    base = os.path.join(outdir, stem)
    canonical_wav = os.path.join(outdir, f".{stem}.16k.wav")
    reserved = [
        canonical_wav,
        base + "-timestamped.txt",
        base + ".txt",
        base + ".srt",
        base + ".json",
        base + "-QA.md",
        base + ".spk.txt",
    ]
    for path in reserved:
        _reserved_output(path)
    wav_fd, wav = tempfile.mkstemp(prefix=".transcribe-wav.", suffix=".wav", dir=outdir)
    os.close(wav_fd)

    try:
        t0 = time.time()
        print(f"[1/4] 오디오 정규화: {os.path.basename(src)}", flush=True)
        to_wav(src, wav)

        print(f"[2/4] 전사 (mlx large-v3-turbo, lang={a.lang}) — 오디오 길이의 약 1/8 소요", flush=True)
        res = transcribe(wav, a.lang)
        segs = res.get("segments") or []

        print(f"[3/4] 저장 ({len(segs)} 세그먼트)", flush=True)
        _atomic_text(
            base + "-timestamped.txt",
            "".join(f"[{hhmmss(s['start'])}] {s['text'].strip()}\n" for s in segs),
        )
        _atomic_text(
            base + ".txt", "\n".join(s["text"].strip() for s in segs) + "\n"
        )
        _atomic_text(
            base + ".srt",
            "".join(
                f"{i}\n{hhmmss(s['start'], True)} --> {hhmmss(s['end'], True)}\n"
                f"{s['text'].strip()}\n\n"
                for i, s in enumerate(segs, 1)
            ),
        )
        _atomic_text(base + ".json", json.dumps(res, ensure_ascii=False, indent=1) + "\n")

        print("[4/5] 결손 스캔", flush=True)
        gaps = scan_gaps(segs, wav)
        real = [g for g in gaps if g[3] == "결손 후보"]
        qa = [
            f"# 전사 QA - {stem}\n\n",
            f"세그먼트 {len(segs)} · 글자수 {sum(len(s['text']) for s in segs):,} · "
            f"길이 {hhmmss(segs[-1]['end']) if segs else '0'}\n\n",
        ]
        if not gaps:
            qa.append(f"{GAP_SEC}초 이상 공백 없음.\n")
        else:
            qa.append("| 시작 | 끝 | 평균 dB | 판정 |\n|---|---|---|---|\n")
            qa.extend(
                f"| {hhmmss(st)} | {hhmmss(en)} | "
                f"{db if db is None else round(db,1)} | {verdict} |\n"
                for st, en, db, verdict in gaps
            )
        if real:
            qa.append(
                f"\n**결손 후보 {len(real)}건. 해당 구간을 직접 들어보고, 빠진 발화가 있으면 "
                "그 구간만 잘라 재전사할 것. 결손을 화자의 침묵으로 읽지 말 것 (7/26 교훈).**\n"
            )
        _atomic_text(base + "-QA.md", "".join(qa))
        if not a.no_diarize:
            print("[5/5] 화자 분리 [추정]", flush=True)
            spk_fd, spk_tmp = tempfile.mkstemp(
                prefix=".diarize.", suffix=".txt", dir=outdir
            )
            os.close(spk_fd)
            r = run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "diarize.py"),
                     wav, "--segments", base + ".json", "--out", spk_tmp]
                    + (["--k", str(a.speakers)] if a.speakers else []))
            if r.returncode == 0 and os.path.isfile(spk_tmp) and os.path.getsize(spk_tmp) > 0:
                os.replace(spk_tmp, base + ".spk.txt")
            else:
                try:
                    os.unlink(spk_tmp)
                except OSError:
                    pass
                sys.exit("화자 분리 실패: " + ((r.stderr or r.stdout).strip() or "빈 산출물"))
            print("   " + ((r.stdout or r.stderr).strip().splitlines() or ["완료"])[-1])

        if a.keep_wav:
            os.replace(wav, canonical_wav)
            wav = None

        print(f"\n완료 ({time.time()-t0:.0f}초): {base}-timestamped.txt")
        if not a.no_diarize:
            print(f"화자: {base}.spk.txt (추정 — 인용 전 청취)")
        print(f"QA: {base}-QA.md — 공백 {len(gaps)}건 중 결손 후보 {len(real)}건")
    finally:
        if wav and os.path.exists(wav):
            os.unlink(wav)


if __name__ == "__main__":
    sys.exit(main())
