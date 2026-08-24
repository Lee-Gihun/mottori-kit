#!/usr/bin/env python3
"""화자 분리 [추정] — 전사 세그먼트를 화자별로 묶는다.

의존성 없이 돈다 (numpy/scipy/sklearn만). 파이프라인:
  세그먼트별 오디오 슬라이스 → MFCC(20) 평균+표준편차 40차 임베딩
  → 켑스트럼 평균 정규화 → L2 정규화 → k=2..6 KMeans → 실루엣 최댓값으로 k 선택

한계 (인용 전에 반드시 기억할 것):
  - 세그먼트 내부의 화자 전환과 겹쳐 말하기는 못 잡는다.
  - 실루엣이 낮으면(0.25 미만) 화자 수 추정을 믿지 말 것. 헤더에 경고가 붙는다.
  - S1/S2는 익명 라벨이다. 실명 귀속은 사람이 내용으로 판정한다.

사용:
  python3 tools/diarize.py <audio> --segments <json|srt> [--out out.spk.txt] [--k N]
"""
import argparse, json, os, re, subprocess, sys
import numpy as np
from scipy.fftpack import dct
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

SR = 16000
NMEL, NCEP = 40, 20
FRAME, HOP = 400, 160          # 25ms / 10ms
MIN_SEG = 0.8                  # 이보다 짧은 세그먼트는 임베딩하지 않는다
KMIN, KMAX = 2, 6
LOW_SIL = 0.25


def load_audio(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                       capture_output=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg 실패: {r.stderr[-500:].decode('utf-8','replace')}")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def mel_filterbank():
    def hz2mel(f): return 2595.0 * np.log10(1.0 + f / 700.0)
    def mel2hz(m): return 700.0 * (10 ** (m / 2595.0) - 1.0)
    lo, hi = hz2mel(80), hz2mel(SR / 2)
    pts = mel2hz(np.linspace(lo, hi, NMEL + 2))
    bins = np.floor((FRAME // 2 + 1) * 2 * pts / SR).astype(int)
    fb = np.zeros((NMEL, FRAME // 2 + 1), dtype=np.float32)
    for i in range(NMEL):
        l, c, r = bins[i], bins[i + 1], bins[i + 2]
        if c == l: c += 1
        if r == c: r += 1
        r = min(r, FRAME // 2)
        if c > r: continue
        fb[i, l:c] = (np.arange(l, c) - l) / max(c - l, 1)
        fb[i, c:r] = (r - np.arange(c, r)) / max(r - c, 1)
    return fb


FB = mel_filterbank()
WIN = np.hamming(FRAME).astype(np.float32)


def mfcc(x):
    if len(x) < FRAME:
        return None
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])            # pre-emphasis
    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * WIN
    spec = np.abs(np.fft.rfft(frames, FRAME)) ** 2 / FRAME
    energy = spec @ FB.T
    logmel = np.log(np.maximum(energy, 1e-10))
    return dct(logmel, type=2, axis=1, norm="ortho")[:, 1:NCEP + 1]


def embed(seg_audio):
    m = mfcc(seg_audio)
    if m is None or len(m) < 5:
        return None
    m = m - m.mean(axis=0, keepdims=True)                  # 켑스트럼 평균 정규화
    v = np.concatenate([m.mean(axis=0), m.std(axis=0)])
    if not np.all(np.isfinite(v)):
        return None
    nrm = np.linalg.norm(v)
    return v / nrm if nrm > 1e-6 else None


def read_segments(path):
    if path.endswith(".json"):
        d = json.load(open(path))
        return [(s["start"], s["end"], s["text"].strip()) for s in d.get("segments", [])]
    out, t = [], open(path, encoding="utf-8", errors="replace").read().strip().split("\n\n")
    for blk in t:
        lines = blk.strip().split("\n")
        if len(lines) < 3: continue
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[1])
        if not m: continue
        g = [int(x) for x in m.groups()]
        st = g[0]*3600 + g[1]*60 + g[2] + g[3]/1000
        en = g[4]*3600 + g[5]*60 + g[6] + g[7]/1000
        out.append((st, en, " ".join(lines[2:]).strip()))
    return out


def hhmm(t):
    return f"{int(t//60):02d}:{int(t%60):02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--segments", required=True, help="전사 결과 .json 또는 .srt")
    ap.add_argument("--out", default=None)
    ap.add_argument("--k", type=int, default=0, help="화자 수를 안다면 고정 (0=자동)")
    a = ap.parse_args()

    segs = read_segments(a.segments)
    if not segs:
        sys.exit("세그먼트를 읽지 못했다")
    audio = load_audio(a.audio)

    vecs, idxs = [], []
    for i, (st, en, _) in enumerate(segs):
        if en - st < MIN_SEG:
            continue
        v = embed(audio[int(st * SR):int(en * SR)])
        if v is not None:
            vecs.append(v); idxs.append(i)
    if len(vecs) < KMIN + 1:
        sys.exit(f"임베딩 가능한 세그먼트가 너무 적다 ({len(vecs)})")
    X = np.array(vecs)

    if a.k >= 2:
        best_k, best_sil = a.k, None
        km = KMeans(n_clusters=a.k, n_init=10, random_state=0).fit(X)
        best_lab = km.labels_
        best_sil = silhouette_score(X, best_lab) if len(set(best_lab)) > 1 else 0.0
    else:
        best_k, best_sil, best_lab = None, -2, None
        for k in range(KMIN, min(KMAX, len(X) - 1) + 1):
            km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
            if len(set(km.labels_)) < 2:
                continue
            s = silhouette_score(X, km.labels_)
            if s > best_sil:
                best_k, best_sil, best_lab = k, s, km.labels_

    # 등장 순서대로 S1, S2... 재명명
    order, seen = {}, 0
    for lab in best_lab:
        if lab not in order:
            seen += 1; order[lab] = seen
    spk = {idxs[j]: f"S{order[best_lab[j]]}" for j in range(len(idxs))}

    out = a.out or (os.path.splitext(a.segments)[0].replace("-timestamped", "") + ".spk.txt")
    with open(out, "w") as f:
        f.write("# 화자 [추정] — MFCC 임베딩 + KMeans (실루엣 기준 k 선택)\n")
        f.write(f"# 화자 수 {best_k} · 실루엣 {best_sil:.3f} · 임베딩 세그먼트 {len(idxs)}/{len(segs)}\n")
        f.write("# 자동 추정이다. 인용 전 원문 청취 필수. 세그먼트 내 화자 전환과 겹쳐 말하기는 못 잡는다.\n")
        if best_sil < LOW_SIL:
            f.write(f"# 경고: 실루엣 {best_sil:.3f} < {LOW_SIL} — 화자 수 추정을 믿지 말 것. "
                    f"화자 수를 안다면 --k 로 고정해 다시 돌릴 것.\n")
        f.write("# S1/S2는 익명 라벨이다. 실명 귀속은 내용으로 판정하고 확정 전 [불확실] 표기.\n\n")
        prev = None
        for i, (st, en, text) in enumerate(segs):
            s = spk.get(i)
            tag = s or "S?"
            if tag != prev:
                f.write(f"\n[{tag}] ({hhmm(st)})\n")
                prev = tag
            f.write(text + "\n")
    print(f"화자 {best_k} · 실루엣 {best_sil:.3f} · {len(idxs)}/{len(segs)} 임베딩 → {out}")


if __name__ == "__main__":
    main()
