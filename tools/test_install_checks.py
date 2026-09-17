#!/usr/bin/env python3
"""설치 검사기 회귀 — linkcheck·doctor·gate가 낯선 설치에서 늑대소년이 되지 않는가.

2026-09-17 독립 감사(Codex)가 잡은 결함을 닫는 픽스처다. 각 테스트는 임시 git 리포를 만들고
그 리포를 인스턴스로 삼아(MOTTORI_INSTANCE) 도구를 서브프로세스로 돌리거나, 검사 함수를
가짜 입력으로 직접 부른다.

  J  linkcheck normal mode는 broken이 있으면 exit 1, 없으면 0 (--issues는 언제나 0)
  F  setup 전 상류 사본: setup이 만드는 경로로 가는 참조는 PENDING, 오타는 BROKEN
     setup 뒤(config 존재): 같은 참조가 없으면 BROKEN (삭제를 숨기지 않는다)
  E  doctor codex armed: 미신뢰만이면 WARN, command invalid·loader error는 FAIL
  git c_git: 2.35 → FAIL, 2.36 → PASS, 버전 문자열 해석 불가 → WARN
  K  gate cmd_check: measure()가 터지면 무출력 0이 아니라 block + pending
  L  공백 든 md 파일명: linkcheck 인증서와 doctor scope 해시가 같다
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

PASSED, FAILED = [], []


def ok(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print(("✓ " if cond else "✗ ") + name + (f": {detail}" if detail and not cond else ""))


def make_repo(with_config=True):
    """엔진 파일 몇 개와 md 문서를 가진 임시 git 리포. tools/는 실제 엔진을 복사한다."""
    root = tempfile.mkdtemp(prefix="install-checks.")
    os.makedirs(os.path.join(root, "tools"))
    for name in ("memlib.py", "linkcheck.py", "doctor.py", "gate.py", "now.py", "hookdiag.py",
                 "coherence.py"):
        src = os.path.join(HERE, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(root, "tools", name))
    os.makedirs(os.path.join(root, "system"))
    os.makedirs(os.path.join(root, "state"))
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("state/\n_private/\nsystem/memory-config.json\nsystem/instance-rules.md\n"
                "system/decisions.md\nsystem/rituals.local.md\n")
    if with_config:
        cfg = json.load(open(os.path.join(ROOT, "templates", "memory-config.json"), encoding="utf-8")) \
            if os.path.exists(os.path.join(ROOT, "templates", "memory-config.json")) else \
            json.load(open(os.path.join(ROOT, "system", "memory-config.json"), encoding="utf-8"))
        cfg.setdefault("instance", {})["name"] = "fixture"
        cfg["instance"]["context"] = "personal"
        cfg["tracks"] = []
        cfg["threads"] = []
        cfg["personal_pointer"] = None      # 새 인스턴스 계약: template 값 그대로(null)
        json.dump(cfg, open(os.path.join(root, "system", "memory-config.json"), "w", encoding="utf-8"))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=fixture@example.invalid", "-c", "user.name=fixture",
                    "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, check=True)
    return root


def run(root, *args, env_extra=None):
    env = dict(os.environ, MOTTORI_INSTANCE=root, MOTTORI_INTERNAL_RUN="")
    env.pop("MOTTORI_INTERNAL_RUN", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([PY, *args], cwd=root, capture_output=True, text=True, env=env)


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------ J · F  linkcheck
def test_linkcheck_exit_codes_and_pending():
    root = make_repo(with_config=False)
    try:
        write(root, "README.md", "see `system/memory-config.json` and [rules](system/instance-rules.md)\n")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("F pre-setup: setup-created targets are PENDING, exit 0",
           r.returncode == 0 and "PENDING" in r.stdout and "broken: 0" in r.stdout, r.stdout[-300:])
        write(root, "system/typo.md", "[x](nope-zz.md)\n")
        subprocess.run(["git", "add", "system/typo.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("J broken → exit 1", r.returncode == 1 and "BROKEN system/typo.md -> nope-zz.md" in r.stdout,
           r.stdout[-300:])
        r = run(root, "tools/linkcheck.py", "--issues")
        ok("J --issues stays exit 0 with #issues trailer", r.returncode == 0 and "#issues 1" in r.stdout,
           r.stdout[-200:])
        os.remove(os.path.join(root, "system", "typo.md"))
        subprocess.run(["git", "rm", "-q", "--cached", "system/typo.md"], cwd=root, check=True)
        # 게이트 기준선도 setup 산출물이다: setup 전 PENDING, setup 뒤 없으면 BROKEN (양방향)
        write(root, "SETUP.md", "baseline lives at `state/.gate-baseline.json`\n")
        subprocess.run(["git", "add", "SETUP.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("F pre-setup: gate baseline reference is PENDING",
           r.returncode == 0 and "PENDING SETUP.md -> state/.gate-baseline.json" in r.stdout, r.stdout[-300:])
        # setup 뒤: config가 생기면 같은 참조가 없을 때 BROKEN이어야 한다 (삭제를 숨기지 않는다)
        write(root, "system/memory-config.json", "{}")
        r = run(root, "tools/linkcheck.py")
        ok("F post-setup: missing instance-rules is BROKEN, exit 1",
           r.returncode == 1 and "BROKEN README.md -> system/instance-rules.md" in r.stdout, r.stdout[-300:])
        ok("F post-setup: missing gate baseline is BROKEN",
           "BROKEN SETUP.md -> state/.gate-baseline.json" in r.stdout, r.stdout[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ L  scope hash with spaces
def test_scope_hash_matches_with_spaced_filename():
    root = make_repo(with_config=True)
    try:
        write(root, "system/a b.md", "# spaced\n")
        subprocess.run(["git", "add", "system/a b.md"], cwd=root, check=True)
        r = run(root, "tools/linkcheck.py")
        ok("L linkcheck runs on spaced filename", r.returncode == 0, r.stdout[-200:])
        code = ("import sys; sys.path.insert(0,'tools'); import doctor; "
                "print(doctor.c_missed_gate()[0])")
        r = run(root, "-c", code)
        ok("L doctor.c_missed_gate PASS after linkcheck (scope hashes agree)",
           r.stdout.strip().endswith("PASS"), r.stdout[-200:] + r.stderr[-200:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ E · git  doctor severities
def test_doctor_codex_armed_and_git_version():
    root = make_repo(with_config=True)
    try:
        code = r'''
import sys, types; sys.path.insert(0, "tools")
import doctor, hookdiag
def fake_list(_root, **kw): return {"hooks": [], "errors": []}
def report(armed, valid=True):
    return {r: {"declared": True, "command_valid": valid, "armed": armed, "matcher_reachable": True}
            for r in ("injector", "side_effect", "guard", "observer", "enforcer", "recovery")}
hookdiag.codex_hooks_list = fake_list
hookdiag.compact_summary = lambda rep: "x"
hookdiag.codex_runtime_report = lambda hooks: report(False)
print("unarmed", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(True)
print("armed", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(False, valid=False)
print("invalid", doctor.c_hook_codex_armed()[0])
hookdiag.codex_runtime_report = lambda hooks: report(True)
hookdiag.codex_hooks_list = lambda _r, **kw: {"hooks": [], "errors": ["boom"]}
print("loader", doctor.c_hook_codex_armed()[0])
class R:
    def __init__(self, out, rc=0): self.stdout=out; self.returncode=rc; self.stderr=""
def fake_sh(*cmd, cwd=None):
    if cmd[:2] == ("git", "--version"): return R(fake_sh.version)
    return R("/tmp/x")
doctor.sh = fake_sh
for v, tag in (("git version 2.35.9", "old"), ("git version 2.36.0", "new"), ("git version 2.50.1 (Apple Git-155)", "apple"), ("weird", "unparsable")):
    fake_sh.version = v
    print(tag, doctor.c_git()[0])
'''
        r = run(root, "-c", code)
        out = dict(l.split(" ", 1) for l in r.stdout.strip().splitlines() if " " in l)
        ok("E codex unarmed → WARN", out.get("unarmed") == "WARN", r.stdout + r.stderr[-300:])
        ok("E codex armed → PASS", out.get("armed") == "PASS", r.stdout)
        ok("E codex command invalid → FAIL", out.get("invalid") == "FAIL", r.stdout)
        ok("E codex loader error → FAIL", out.get("loader") == "FAIL", r.stdout)
        ok("git 2.35 → FAIL", out.get("old") == "FAIL", r.stdout)
        ok("git 2.36 → PASS", out.get("new") == "PASS", r.stdout)
        ok("git 2.50 (Apple) → PASS", out.get("apple") == "PASS", r.stdout)
        ok("git unparsable → WARN", out.get("unparsable") == "WARN", r.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ K  gate fail-closed
def test_gate_check_blocks_when_measure_raises():
    root = make_repo(with_config=True)
    try:
        code = r'''
import sys, os, io, json; sys.path.insert(0, "tools")
import gate
gate._mark(gate.DIRTY())
def boom(*a, **k): raise RuntimeError("measure exploded")
gate.measure = boom
sys.stdin = io.StringIO("{}")
buf = io.StringIO(); real = sys.stdout; sys.stdout = buf
rc = gate.cmd_check()
sys.stdout = real
out = buf.getvalue()
print("rc", rc)
print("pending", os.path.exists(gate.PENDING()))
try:
    d = json.loads(out)
    print("json", d.get("decision") == "block" and isinstance(d.get("reason"), str) and bool(d.get("reason")))
except Exception as e:
    print("json", False, repr(out[:120]))
# resume 경로: 예외여도 pending 유지 + UserPromptSubmit 경고 JSON
gate._mark(gate.DIRTY())
buf = io.StringIO(); sys.stdout = buf
rc2 = gate.cmd_resume()
sys.stdout = real
out2 = buf.getvalue()
try:
    d2 = json.loads(out2)
    h = d2.get("hookSpecificOutput", {})
    print("resume", rc2 == 0 and h.get("hookEventName") == "UserPromptSubmit"
          and "게이트" in h.get("additionalContext", "") and os.path.exists(gate.PENDING()))
except Exception as e:
    print("resume", False, repr(out2[:120]))
'''
        r = run(root, "-c", code)
        lines = dict(l.split(" ", 1) for l in r.stdout.strip().splitlines() if " " in l)
        ok("K gate exception → pending marker kept", lines.get("pending") == "True", r.stdout + r.stderr[-300:])
        ok("K gate exception → Stop block JSON with decision=block and reason",
           lines.get("json", "").startswith("True"), r.stdout + r.stderr[-300:])
        ok("K resume exception → UserPromptSubmit warning JSON, pending kept",
           lines.get("resume", "").startswith("True"), r.stdout + r.stderr[-300:])
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------ M  NOW personal pointer
def test_now_renders_unspecified_personal_pointer():
    root = make_repo(with_config=True)
    try:
        r = run(root, "tools/now.py", "log", "[system/state] fixture")
        r = run(root, "tools/now.py", "render")
        now = open(os.path.join(root, "state", "NOW.md"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(root, "state", "NOW.md")) else ""
        ok("M fresh NOW says 정본 미지정, never `None`",
           "정본 미지정" in now and "`None`" not in now, (now[:300] or r.stderr[-300:]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_linkcheck_exit_codes_and_pending, test_scope_hash_matches_with_spaced_filename,
               test_doctor_codex_armed_and_git_version, test_gate_check_blocks_when_measure_raises,
               test_now_renders_unspecified_personal_pointer):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            FAILED.append(fn.__name__)
            print(f"✗ {fn.__name__}: {type(e).__name__}: {e}")
    print(f"install checks: {len(PASSED)}/{len(PASSED) + len(FAILED)} passed")
    sys.exit(0 if not FAILED else 1)
