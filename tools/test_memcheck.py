#!/usr/bin/env python3
"""check 검출기의 픽스처 테스트 — 과거 사고를 재현해 잡히는지 확인한다.

goal 요구사항: "check 검출기는 과거 사고(8/8 낡은 인덱스, tracker 드리프트) 재현
픽스처로 검증." 통과 기준: 두 픽스처 모두에서 해당 검출기가 발화.
"""
import datetime
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M
import importlib
now = importlib.import_module("now")


def fixture_8_8_stale_index(tmp):
    """사고 재현 1: 2026-08-08 시점의 실제 MEMORY.md 인덱스 줄 —
    '트랙 완주(8/8)→다음 국면(응답 대기)' 류의 상태 줄이 8/15까지 정본 행세."""
    mem = os.path.join(tmp, "memory")
    os.makedirs(mem)
    open(os.path.join(mem, "MEMORY.md"), "w", encoding="utf-8").write(
        "# Memory Index\n\n"
        "- [Session state](session-state-handoff.md) — 트랙 완주(8/8)"
        "→다음 국면(응답 대기) · 후속 B 화 8/11 · 후속 C 월 8/10\n")
    open(os.path.join(mem, "session-state-handoff.md"), "w").write("---\ntype: user\n---\nx")
    return mem


# 픽스처 전용 트랙. **라이브 config를 쓰지 않는다** (2026-08-24 적대 검증).
# 이전 판은 config에 `jobs` 트랙이 등록돼 있어야만 통과했다. 즉 회귀 테스트가
# 인스턴스 설정에 의존해서, 트랙이 없는 새 인스턴스에서는 검출기가 멀쩡해도 실패했다.
# 테스트는 자기가 재려는 것만 재야 한다.
FIXTURE_TRACKS = [("demo", "데모", "demo/tracker.md")]


def fixture_tracker_drift(tmp):
    """사고 재현 2: journal에는 나중 사건이 있는데 트랙 정본 파일은 그 전에 멈춤."""
    root = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(root, "demo"))
    tracker = os.path.join(root, "demo", "tracker.md")
    open(tracker, "w", encoding="utf-8").write("# tracker\n마지막 업데이트: 2026-08-08\n")
    old = datetime.datetime(2026, 8, 8, 14, 30).timestamp()
    os.utime(tracker, (old, old))

    state = os.path.join(tmp, "state")
    os.makedirs(state)
    open(os.path.join(state, "journal-2026-08.md"), "w", encoding="utf-8").write(
        "# journal\n\n- 2026-08-13T10:00+09:00 [demo/state] 후속 사건 발생\n")
    return root, state


def run():
    tmp = tempfile.mkdtemp(prefix="memcheck-fixture-")
    failures = []
    try:
        # --- 픽스처 1: 낡은 인덱스 ---
        mem = fixture_8_8_stale_index(tmp)
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            now.check(memory_dir=mem, root=os.path.join(tmp, "empty"))
        out1 = buf.getvalue()
        if "[인덱스 휘발성]" in out1:
            print("픽스처 1 (8/8 낡은 인덱스): ✓ 검출")
        else:
            failures.append("픽스처 1: 인덱스 휘발성 미검출\n" + out1)

        # --- 픽스처 2: tracker 드리프트 ---
        root, state = fixture_tracker_drift(tmp)
        orig_state, orig_tracks = M.STATE, M.TRACKS
        M.STATE = state           # journal 위치 재지정
        M.TRACKS = FIXTURE_TRACKS  # 라이브 config와 격리
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                now.check(memory_dir=os.path.join(tmp, "nomem"), root=root)
            out2 = buf.getvalue()
        finally:
            M.STATE, M.TRACKS = orig_state, orig_tracks
        if "[정본 낙후] demo/tracker.md" in out2:
            print("픽스처 2 (tracker 드리프트): ✓ 검출")
        else:
            failures.append("픽스처 2: 정본 낙후 미검출\n" + out2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("\n실패:")
        for f in failures:
            print(" ", f)
        return 1
    print("전 픽스처 통과")
    return 0


if __name__ == "__main__":
    sys.exit(run())
