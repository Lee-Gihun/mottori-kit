#!/usr/bin/env python3
# Matrix coverage: tools/i18n.py
import os
import json
import re
import shutil
import string
import subprocess
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import i18n


HANGUL = re.compile(r"[\uac00-\ud7a3]")
PASSED = 0
FAILED = []
SKIPPED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("✓ " + name)
    else:
        FAILED.append(name)
        print("✗ " + name + (": " + detail if detail else ""))


def run(*args, cwd=ROOT, lang="en"):
    env = dict(os.environ, MOTTORI_LANG=lang, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)


def test_english_surfaces():
    # 설치된 인스턴스(setup.sh 없음)는 journal·track 이름 등 사용자 데이터가 그 언어라 "EN 출력에 한글 0"을
    # 잴 수 없고 setup fixture도 만들 수 없다. 건너뛴 사실은 요약 줄에 남긴다 (KIT-DR-012: 판정은 영수증으로만).
    if not os.path.isfile(os.path.join(ROOT, "setup.sh")):
        SKIPPED.append("EN surfaces (installed instance without setup.sh: user data may be Korean; "
                       "covered by tools/test_fresh_install.sh with MOTTORI_LANG=en in the kit)")
        print("- EN surfaces: not applicable here — " + SKIPPED[-1])
        return
    doctor = run(sys.executable, "tools/doctor.py")
    check("EN doctor stdout has no Hangul", not HANGUL.search(doctor.stdout), doctor.stdout[-500:])

    links = run(sys.executable, "tools/linkcheck.py")
    check("EN linkcheck stdout has no Hangul", not HANGUL.search(links.stdout), links.stdout[-500:])

    parent = tempfile.mkdtemp(prefix="i18n-setup-")
    clone = os.path.join(parent, "kit")
    try:
        cloned = subprocess.run(["git", "clone", "-q", ROOT, clone], capture_output=True, text=True)
        check("setup fixture is a temporary clone", cloned.returncode == 0, cloned.stderr[-300:])
        if cloned.returncode != 0:
            return
        patch = subprocess.run(
            ["git", "diff", "--binary", "HEAD"], cwd=ROOT, capture_output=True
        )
        applied = subprocess.run(
            ["git", "apply"], cwd=clone, input=patch.stdout, capture_output=True
        ) if patch.returncode == 0 and patch.stdout else None
        untracked = subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard", "-z"],
            cwd=ROOT, capture_output=True
        )
        copied = untracked.returncode == 0
        if copied:
            for raw in untracked.stdout.split(b"\0"):
                if not raw:
                    continue
                rel = os.fsdecode(raw)
                source = os.path.join(ROOT, rel)
                if not os.path.isfile(source):
                    continue
                destination = os.path.join(clone, rel)
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)
        staged = subprocess.run(["git", "add", "-A"], cwd=clone, capture_output=True)
        mirrored = (patch.returncode == 0 and (applied is None or applied.returncode == 0)
                    and copied and staged.returncode == 0)
        detail = b"\n".join(filter(None, (
            patch.stderr,
            applied.stderr if applied is not None else b"",
            untracked.stderr,
            staged.stderr,
        ))).decode("utf-8", errors="replace")[-500:]
        check("setup fixture mirrors worktree", mirrored, detail)
        if not mirrored:
            return
        setup = run("bash", "setup.sh", "--name", "x", "--context", "personal", cwd=clone)
        check("EN setup stdout has no Hangul", not HANGUL.search(setup.stdout), setup.stdout[-800:])
        check("EN setup completes", setup.returncode == 0, (setup.stdout + setup.stderr)[-1200:])
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_korean_compatibility():
    old = os.environ.get("MOTTORI_LANG")
    os.environ["MOTTORI_LANG"] = "ko"
    try:
        expected = {
            "doctor.node_missing": "node 없음 — 정원사(wf_gardener.js)만 못 쓴다",
            "doctor.finish_fail": "\nFAIL 2개를 먼저 고쳐라. 그 전에는 이 인스턴스의 상태 자동화를 믿지 마라.",
            "linkcheck.pending_count": " · pending(setup 전): 3",
            "gate.baseline_absent": "게이트 기준선이 없다. 지운 것과 처음 설치한 것을 기계가 구분할 수 없어서 자동으로 채택하지 않는다. `python3 tools/gate.py baseline`을 직접 돌려라.",
            "setup.already": "이미 세팅돼 있다: system/memory-config.json",
        }
        actual = {
            "doctor.node_missing": i18n.t("doctor.node_missing"),
            "doctor.finish_fail": i18n.t("doctor.finish_fail", count=2),
            "linkcheck.pending_count": i18n.t("linkcheck.pending_count", count=3),
            "gate.baseline_absent": i18n.t("gate.baseline_absent"),
            "setup.already": i18n.t("setup.already", path="system/memory-config.json"),
        }
        for key in expected:
            check("KO compatibility: " + key, actual[key] == expected[key], repr(actual[key]))
    finally:
        if old is None:
            os.environ.pop("MOTTORI_LANG", None)
        else:
            os.environ["MOTTORI_LANG"] = old


def test_catalog_complete():
    missing = {key: sorted({"en", "ko"} - set(row)) for key, row in i18n.STRINGS.items()
               if set(row) != {"en", "ko"}}
    empty = {key: lang for key, row in i18n.STRINGS.items() for lang, value in row.items()
             if not isinstance(value, str) or not value}
    check("every i18n key has EN and KO", not missing, repr(missing))
    check("every i18n value is a nonempty string", not empty, repr(empty))
    formatter = string.Formatter()
    mismatched = {}
    for key, row in i18n.STRINGS.items():
        fields = [{name for _, name, _, _ in formatter.parse(row[lang]) if name}
                  for lang in ("en", "ko")]
        if fields[0] != fields[1]:
            mismatched[key] = fields
    check("EN and KO placeholders match", not mismatched, repr(mismatched))


def test_language_selection():
    saved = {name: os.environ.get(name) for name in ("MOTTORI_LANG", "LANG", "LC_ALL")}
    try:
        os.environ.pop("MOTTORI_LANG", None)
        os.environ["LANG"] = "ko_KR.UTF-8"
        os.environ["LC_ALL"] = ""
        check("Korean locale selects KO", i18n.language() == "ko")
        os.environ["MOTTORI_LANG"] = "en"
        check("MOTTORI_LANG overrides locale", i18n.language() == "en")
        os.environ.pop("MOTTORI_LANG", None)
        os.environ["LANG"] = "C.UTF-8"
        check("non-Korean locale selects EN", i18n.language() == "en")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_sessionstart_fallback_is_bilingual():
    for rel in ((".claude", "settings.json"), (".codex", "hooks.json")):
        payload = json.load(open(os.path.join(ROOT, *rel), encoding="utf-8"))
        command = payload["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        check("bilingual fallback: " + rel[0],
              "상태 자동 주입이 실패했다" in command and "State injection failed" in command,
              command)


if __name__ == "__main__":
    if "--full" in sys.argv:
        test_english_surfaces()
    else:
        SKIPPED.append("EN fresh-install surfaces (run this suite with --full)")
        print("- EN fresh-install surfaces: deferred to --full")
    test_korean_compatibility()
    test_catalog_complete()
    test_language_selection()
    test_sessionstart_fallback_is_bilingual()
    total = PASSED + len(FAILED)
    skipped = f" · not applicable {len(SKIPPED)}" if SKIPPED else ""
    print(f"i18n: {PASSED}/{total} passed{skipped}")
    sys.exit(0 if not FAILED else 1)
