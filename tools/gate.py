#!/usr/bin/env python3
"""gate — 편집이 있었던 턴이 끝날 때 자동으로 도는 검증 게이트.

**왜 있나.** 2026-08-24 하루에 같은 실패를 세 번 했다. `rituals.md`에 "재편 후 linkcheck 필수"가
명시돼 있는데 새 산출물(킷)을 만들고 안 돌려서 깨진 참조 27개가 "검증 완료"로 나갔다.
조건부 문서는 **내가 읽어야겠다고 판단해야만** 열리고, 그 판단이 실패하는 것이 문제였다.

스킬로는 안 된다. 설명이 맞으면 뜨지만 **반드시 뜨지는 않는다** — `P(발동|해당사건) > 0`과
`P = 1`은 다르다. 검증은 계약이어야 하므로 결정적 훅이다.

**검사기 계약 (v2).** 각 검사기는 `--issues`로
    <안정ID>\\t<표시문구>      ← 시간이 만든 것은 ID 앞에 `~`
    #issues <N>               ← 반드시 마지막 줄
을 내고 **이슈 유무와 무관하게 exit 0**으로 끝난다. 종료코드는 "측정이 됐는가"만 뜻한다.

게이트가 측정 실패로 보는 것 (전부 차단):
  - nonzero exit
  - 트레일러가 없거나 마지막 줄이 아님
  - 선언 수와 실제 gated ID 수 불일치
  - 기준선과 **검사기 목록이 다름** (검사기를 지워서 우회하는 것을 막는다)

**개수가 아니라 집합이다.** 개수는 치환에 눈이 멀었다 — 링크 하나 고치고 하나 깨면 같은 수라
통과했다. `현재 - 기준선`이 비지 않으면 막고, 현재가 기준선의 진부분집합일 때만 당긴다.

**기준선은 사람만 만든다.** 삭제와 첫 설치를 기계가 구분할 수 없다. 세 운영 명령(check·resume·
precommit)은 기준선이 없으면 각자의 방식으로 거부하고, 쓰기는 `gate.py baseline` 하나에만 있다.
(줄어들 때 당기는 것은 조이는 방향이라 허용한다.)

**범위 (정직하게).** Stop 훅은 `Write|Edit|NotebookEdit`만 본다. Bash 편집·외부 writer·
Codex 편집·interrupt는 못 본다. 그래서 후방선 둘이 있다.
  gate.py precommit   커밋될 index를 검사 (`tools/install_hooks.sh`로 설치)
  gate.py resume      UserPromptSubmit에서 남은 dirty와 미해결 실패를 회수
`git commit --no-verify`는 전부 우회한다. 계약이 아니라 후방선이다.

사용:
    python3 tools/gate.py dirty     PostToolUse 훅에서 (표시만)
    python3 tools/gate.py check     Stop 훅에서
    python3 tools/gate.py resume    UserPromptSubmit 훅에서
    python3 tools/gate.py precommit pre-commit 훅에서 (fail closed)
    python3 tools/gate.py selfcheck direct/precommit gated ID 집합 비교
    python3 tools/gate.py approve-adoption --adopt <checker:issue-id> ...  신규 이슈 채택 승인
    python3 tools/gate.py baseline  현재 이슈 집합을 기준선으로 (사람만)
    python3 tools/gate.py status    지금 상태 보기
"""
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import memlib as M
from i18n import t

# **실행 root를 자기 파일에서 유도한다** (codex 라운드 4). `MOTTORI_INSTANCE`로 깨끗한 다른
# 클론을 가리키면 깨진 index가 통과했다. 훅은 이 변수를 지우고, 게이트는 불일치면 거부한다.
SELF_ROOT = os.path.dirname(HERE)

BASELINE = os.path.join(M.STATE, ".gate-baseline.json")

CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py"), "--issues"]),
    ("evidencecheck", [sys.executable, os.path.join(HERE, "evidencecheck.py"), "--issues"]),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check", "--issues"]),
    # 생성 파일(review manifest)이 index보다 낡은 채 커밋되는 경로를 닫는다 (2026-09-18 CI 실측). 킷 트리에만 해당.
    ("manifest", [sys.executable, os.path.join(HERE, "manifest_build.py"), "--issues"]),
]
TEST_EVIDENCE_ACTIVE = "MOTTORI_TEST_EVIDENCE_ACTIVE"
TEST_LOG_ENV = "MOTTORI_TEST_LOG"
TEST_RUN_ID_ENV = "MOTTORI_TEST_RUN_ID"
TEST_MARKER = re.compile(
    r"test:(tools/test_[A-Za-z0-9_]+\.py)::[A-Za-z_][A-Za-z0-9_]*"
)
TEST_ID_MARKER = re.compile(
    r"test:(tools/test_[A-Za-z0-9_]+\.py::[A-Za-z_][A-Za-z0-9_]*)"
)
EVIDENCE_TARGETS = (
    "system/kit-decisions.md", "CHANGELOG.md", "system/enforcement-matrix.md",
)


def _root_ok():
    return os.path.realpath(M.ROOT) == os.path.realpath(SELF_ROOT)


def _gitdir():
    d = subprocess.run(["git", "-C", M.ROOT, "rev-parse", "--git-dir"],
                       capture_output=True, text=True).stdout.strip()
    if not d:
        return None
    return d if os.path.isabs(d) else os.path.join(M.ROOT, d)


def _ephem(name):
    """마커는 **추적 밖**에 산다. `state/`에 뒀더니 커밋돼서 리포에 들어갔다 (실측)."""
    g = _gitdir()
    return os.path.join(g, name) if g else os.path.join(M.STATE, "." + name)


DIRTY = lambda: _ephem("mottori-gate-dirty")
PENDING = lambda: _ephem("mottori-gate-pending")     # 막힌 뒤 아직 재검증 안 된 상태
LOCK = lambda: _ephem("mottori-gate-lock")
SIGNING_KEY = lambda: _ephem("mottori-gate-key")


def _approval_path():
    gitdir = _gitdir()
    return os.path.join(gitdir, "mottori-gate-adoption-approval.json") if gitdir else None


APPROVAL = _approval_path


@contextlib.contextmanager
def _lock(timeout=150):
    """dirty 표시·검사·기준선 갱신을 직렬화한다.

    없으면 lost wakeup이 난다 (codex 라운드 4 재현): A가 검사 중일 때 B가 편집하고 dirty를
    다시 찍으면, A가 옛 결과로 통과한 뒤 B의 마커까지 지웠다."""
    p = LOCK()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    f = open(p, "w")
    end = time.time() + timeout
    got = False
    while time.time() < end:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            got = True
            break
        except OSError:
            time.sleep(0.05)
    try:
        yield got
    finally:
        if got:
            with contextlib.suppress(OSError):
                fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _issues(cmd, cwd=None, instance=None, extra_env=None):
    """검사기 하나 → 게이트가 무는 ID 집합. 측정 실패면 None."""
    env = dict(os.environ, MOTTORI_INTERNAL_RUN="1")
    if instance is None:
        env.pop("MOTTORI_INSTANCE", None)
    else:
        env["MOTTORI_INSTANCE"] = instance
    if extra_env:
        env.update(extra_env)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           cwd=cwd or M.ROOT, env=env, timeout=120)
    except Exception:
        return None
    if r.returncode != 0:
        return None                      # issues 모드는 이슈가 있어도 0으로 끝나야 한다
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or not lines[-1].startswith("#issues "):
        return None                      # 트레일러는 반드시 마지막 줄
    try:
        declared = int(lines[-1].split()[1])
    except (IndexError, ValueError):
        return None
    ids = {l.split("\t", 1)[0] for l in lines[:-1]}
    gated = {i for i in ids if not i.startswith("~")}
    if declared != len(gated):
        return None
    return gated


def _ensure_git_tree(tree):
    """Give an extracted staged tree local Git metadata before support files are created."""
    # The tree must be its own repository. An extracted tree under the parent's .git resolves to the
    # parent's git dir, so suites that touch git then hit the parent's index from the wrong root
    # (2026-09-18: "index file open failed: Not a directory" during pre-commit evidence collection).
    git_probe = subprocess.run(
        ["git", "-C", tree, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if git_probe.returncode == 0 and os.path.realpath(git_probe.stdout.strip()) == os.path.realpath(tree):
        return True
    fixture_commands = (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=gate-fixture",
         "-c", "user.email=gate-fixture@example.invalid",
         "commit", "-qm", "staged test evidence fixture"],
    )
    for command in fixture_commands:
        initialized = subprocess.run(
            command, cwd=tree, env=os.environ, capture_output=True, text=True
        )
        if initialized.returncode != 0:
            return False
    return True


def _cited_test_ids(tree):
    """Return (suite paths, test IDs) cited by test markers in the tree's evidence targets."""
    suites, ids = set(), set()
    for rel in EVIDENCE_TARGETS:
        try:
            text = open(os.path.join(tree, rel), encoding="utf-8").read()
        except OSError:
            continue
        suites.update(match.group(1) for match in TEST_MARKER.finditer(text))
        ids.update(match.group(1) for match in TEST_ID_MARKER.finditer(text))
    return suites, ids


def _log_covers(log_path, run_id, ids):
    """True when the inherited log already holds a fresh RAN record of this run for every cited ID."""
    import evidencecheck as EC
    ran, _now = EC._load_test_runs(log_path, run_id)
    return ran is not None and ids <= ran


def _refresh_test_evidence(tree):
    """Create a fresh RAN log for every suite cited by a test marker.

    Evidence is reused, not recomputed: when the caller inherited a log and a run ID and that log
    already holds a fresh record of the same run for every cited test, nothing is re-executed. Before
    this rule every gate run inside a fixture re-ran all cited suites (14 of them), and suites that
    exercise the gate in fixtures do so about twenty times; CI's regression step went from 2.5 to
    32 minutes and one cell hit the 40-minute limit (2026-09-18, ad032ec). Fixtures that need a real
    execution use their own empty log or another run ID, as the evidencecheck suite does."""
    if not _ensure_git_tree(tree):
        return os.environ.get(TEST_LOG_ENV), False
    if os.environ.get(TEST_EVIDENCE_ACTIVE) == "1":
        return os.environ.get(TEST_LOG_ENV), True
    suites, cited_ids = _cited_test_ids(tree)
    inherited_log = os.environ.get(TEST_LOG_ENV)
    inherited_run = os.environ.get(TEST_RUN_ID_ENV, "")
    if (inherited_log and re.fullmatch(r"[A-Za-z0-9._+-]{1,128}", inherited_run)
            and _log_covers(inherited_log, inherited_run, cited_ids)):
        return inherited_log, True
    # evidencecheck's own end-to-end gate fixture must run after every other
    # cited suite has written its records, otherwise its nested gate sees a
    # legitimately incomplete in-progress log.
    ordered = sorted(suites, key=lambda rel: (rel == "tools/test_evidencecheck.py", rel))
    raw_log = os.environ.get(TEST_LOG_ENV)
    log_path = raw_log or _ephem("mottori-test-runs.log")
    inherited_run_id = os.environ.get(TEST_RUN_ID_ENV, "")
    run_id = (inherited_run_id if re.fullmatch(r"[A-Za-z0-9._+-]{1,128}", inherited_run_id)
              else "gate-" + secrets.token_hex(16))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        if raw_log:
            open(log_path, "a", encoding="utf-8").close()
        else:
            open(log_path, "w", encoding="utf-8").close()
    except OSError:
        return log_path, False
    env = dict(os.environ, **{
        TEST_LOG_ENV: log_path,
        TEST_RUN_ID_ENV: run_id,
        TEST_EVIDENCE_ACTIVE: "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    for rel in ordered:
        if not os.path.isfile(os.path.join(tree, rel)):
            return log_path, False
        try:
            result = subprocess.run(
                [sys.executable, rel], cwd=tree, env=env,
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return log_path, False
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()[-12:]
            print(
                f"[gate] test evidence suite failed: {rel}: " + " | ".join(tail),
                file=sys.stderr,
            )
            return log_path, False
    os.environ[TEST_LOG_ENV] = log_path
    os.environ[TEST_RUN_ID_ENV] = run_id
    return log_path, True


def measure(tree=None, filelist=None):
    out = {}
    checked_tree = tree or M.ROOT
    _test_log, test_evidence_ok = _refresh_test_evidence(checked_tree)
    for name, cmd in CHECKS:
        c = list(cmd)
        if tree and name == "linkcheck":
            c += ["--tree", tree] + (["--filelist", filelist] if filelist else [])
        if name == "evidencecheck" and not test_evidence_ok:
            out[name] = None
            continue
        if tree and name == "evidencecheck":
            # 커밋될 index의 검사기와 문서를 함께 쓴다. run과 인스턴스 DR만 로컬 overlay에서 찾는다.
            staged_checker = os.path.join(tree, "tools", "evidencecheck.py")
            c = [sys.executable, staged_checker, "--issues", "--tree", tree,
                 "--local-root", M.ROOT]
        if tree and name == "now-check":
            # pre-commit은 worktree가 아니라 index에서 꺼낸 엔진과 상태를 검사해야 한다.
            # 인스턴스 저장소(visa)는 config/state가 tracked라 extracted tree가 정본이고,
            # 배포 킷은 둘 다 의도적으로 ignored라 staged 엔진을 현재 local instance에 대입한다.
            staged_now = os.path.join(tree, "tools", "now.py")
            staged_config = os.path.join(tree, "system", "memory-config.json")
            instance = tree if os.path.isfile(staged_config) else M.ROOT
            c = [sys.executable, staged_now, "check", "--issues", "--portable"]
            out[name] = _issues(c, cwd=instance, instance=instance)
        elif tree and name == "manifest":
            staged_manifest = os.path.join(tree, "tools", "manifest_build.py")
            c = [sys.executable, staged_manifest, "--issues"]
            out[name] = _issues(
                c,
                cwd=tree,
                extra_env={
                    "MOTTORI_APPROVAL_MODE": "staged",
                    "MOTTORI_APPROVAL_REPO": M.ROOT,
                },
            )
        else:
            out[name] = _issues(c, cwd=tree if tree else None)
    return out


def _load_baseline():
    """(집합 dict, 상태). 상태: ok · absent · corrupt."""
    if not os.path.exists(BASELINE):
        return {}, "absent"
    try:
        raw = json.load(open(BASELINE, encoding="utf-8"))
        if not isinstance(raw, dict) or not raw:
            return {}, "corrupt"
        if raw.get("schema_version") in (2, 3):
            issues = raw.get("issues")
            payload_hash = raw.get("payload_sha256")
            signature = raw.get("signature")
            if not isinstance(issues, dict) or not isinstance(payload_hash, str) \
                    or not isinstance(signature, str):
                return {}, "corrupt"
            if raw["schema_version"] == 3:
                adoptions = raw.get("adoptions")
                if not _valid_adoptions(adoptions):
                    return {}, "corrupt"
                payload = _baseline_payload_v3(issues, adoptions)
            else:
                payload = _baseline_payload(issues)
            if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), payload_hash):
                return {}, "corrupt"
            try:
                key = open(SIGNING_KEY(), "rb").read()
            except OSError:
                return {}, "corrupt"
            expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return {}, "corrupt"
            return {k: set(v) for k, v in issues.items()}, "ok"
        # Upgrade bridge: an old unsigned baseline is accepted only until install_hooks --repair
        # creates the repository-local key and seals it. Once a key exists, unsigned means tampered.
        if os.path.exists(SIGNING_KEY()):
            return {}, "corrupt"
        return {k: set(v) for k, v in raw.items()}, "ok"
    except Exception:
        return {}, "corrupt"


def _baseline_payload(issues):
    canonical = {k: sorted(v) for k, v in issues.items()}
    return json.dumps(canonical, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _file_sha256(path):
    with open(path, "rb") as source:
        return hashlib.sha256(source.read()).hexdigest()


def _issues_sha256(issues):
    return hashlib.sha256(_baseline_payload(issues)).hexdigest()


def _valid_adoptions(adoptions):
    return (isinstance(adoptions, list)
            and all(isinstance(row, dict)
                    and set(row) == {"checker", "issue_id", "adopted_at"}
                    and all(isinstance(row[key], str) and row[key]
                            for key in ("checker", "issue_id", "adopted_at"))
                    for row in adoptions))


def _valid_approval_adoptions(adoptions):
    return (isinstance(adoptions, list)
            and all(isinstance(row, dict)
                    and set(row) == {"checker", "issue_id"}
                    and all(isinstance(row[key], str) and row[key]
                            for key in ("checker", "issue_id"))
                    for row in adoptions))


def _approval_payload(baseline_sha256, target_issues_sha256, adoptions):
    payload = {
        "schema_version": 1,
        "baseline_sha256": baseline_sha256,
        "target_issues_sha256": target_issues_sha256,
        "adoptions": adoptions,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _approval_document(cur, adopted):
    baseline_sha256 = _file_sha256(BASELINE)
    target_issues_sha256 = _issues_sha256(cur)
    adoptions = [{"checker": checker, "issue_id": issue_id}
                 for checker, issue_id in sorted(adopted)]
    payload = _approval_payload(baseline_sha256, target_issues_sha256, adoptions)
    key = open(SIGNING_KEY(), "rb").read()
    return {
        "schema_version": 1,
        "baseline_sha256": baseline_sha256,
        "target_issues_sha256": target_issues_sha256,
        "adoptions": adoptions,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signature": hmac.new(key, payload, hashlib.sha256).hexdigest(),
    }


def _baseline_payload_v3(issues, adoptions):
    payload = {
        "issues": {k: sorted(v) for k, v in issues.items()},
        "adoptions": adoptions,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _baseline_adoptions():
    try:
        raw = json.load(open(BASELINE, encoding="utf-8"))
    except Exception:
        return []
    if raw.get("schema_version") != 3 or not _valid_adoptions(raw.get("adoptions")):
        return []
    _issues, state = _load_baseline()
    return list(raw["adoptions"]) if state == "ok" else []


def _save_baseline(cur, adopted=()):
    os.makedirs(M.STATE, exist_ok=True)
    tmp = BASELINE + ".tmp"
    issues = {k: sorted(v) for k, v in cur.items()}
    if os.path.exists(SIGNING_KEY()):
        key = open(SIGNING_KEY(), "rb").read()
        adoptions = _baseline_adoptions()
        adopted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        adoptions.extend({"checker": checker, "issue_id": issue_id, "adopted_at": adopted_at}
                         for checker, issue_id in adopted)
        payload = _baseline_payload_v3(issues, adoptions)
        document = {
            "schema_version": 3,
            "issues": issues,
            "adoptions": adoptions,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "signature": hmac.new(key, payload, hashlib.sha256).hexdigest(),
        }
    else:
        document = issues
    with open(tmp, "w", encoding="utf-8") as output:
        json.dump(document, output, ensure_ascii=False, indent=0)
    os.replace(tmp, BASELINE)


def _verdict(cur, base, state):
    """(막을 이유 or None, 기준선을 당길지). **채택은 절대 안 한다.**"""
    dead = sorted(k for k, v in cur.items() if v is None)
    if dead:
        return t("gate.checker_dead", items=", ".join(dead)), False
    if state == "corrupt":
        return t("gate.baseline_corrupt", path=BASELINE), False
    if state == "absent":
        return t("gate.baseline_absent"), False
    only_b = sorted(set(base) - set(cur))
    if only_b:
        # 검사기가 사라진 것은 검사기를 지워서 통과시키는 경로다. 막는다.
        return t("gate.checks_changed", only_base=t("gate.only_base", items=", ".join(only_b)),
                 only_current=""), False
    # 검사기가 늘어난 것은 빈 기준선으로 취급한다: 새 검사기의 이슈는 전부 "새 이슈"라 숨길 수 없고,
    # 이슈 0이면 기준선에 그 키를 기록한다. 2026-09-18 실측: 검사기 추가 커밋이 "목록이 다르다"와
    # "sealed tree가 clean하지 않으면 baseline 금지"에 동시에 걸려 커밋도 재기준선도 불가능한 교착이었다.
    grown = sorted(set(cur) - set(base))
    base = {k: base.get(k, set()) for k in cur}

    new = {k: sorted(cur[k] - base[k]) for k in cur}
    new = {k: v for k, v in new.items() if v}
    if new:
        detail = " · ".join(f"{k}: " + "; ".join(v[:4])
                            + (t("gate.more", count=len(v)-4) if len(v) > 4 else "")
                            for k, v in new.items())
        return t("gate.new_issues", detail=detail), False

    shrank = (all(cur[k] <= base[k] for k in cur) and any(cur[k] < base[k] for k in cur))
    return None, shrank or bool(grown)


def _block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _mark(p, val="1"):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(val)


def cmd_dirty():
    with _lock(timeout=150) as got:
        # 잠금을 못 얻어도 표시는 남긴다. 안 남기는 쪽이 더 나쁜 실패다.
        _mark(DIRTY(), str(time.time_ns()))
    return 0


def _resolve_adoptions(requested, new_issues):
    """Resolve checker-qualified issue IDs to the complete set of new issue pairs."""
    pairs = {(checker, issue_id) for checker, issue_ids in new_issues.items()
             for issue_id in issue_ids}
    resolved = []
    for qualified in requested:
        checker, separator, issue_id = qualified.partition(":")
        pair = (checker, issue_id)
        if not separator or not checker or not issue_id or pair not in pairs:
            return None, f"--adopt {qualified!r} must name one new checker:issue-id pair"
        if pair in resolved:
            return None, f"--adopt {qualified!r} was repeated"
        resolved.append(pair)
    missing = sorted(pairs - set(resolved))
    if missing:
        detail = ", ".join(f"{checker}:{issue_id}" for checker, issue_id in missing)
        return None, "sealed baseline has unadopted new issues: " + detail
    return sorted(resolved), None


def _load_adoption_approval(cur, new_issues):
    """Load an immutable-control-plane approval bound to this baseline and measurement."""
    path = APPROVAL()
    if path is None:
        return None, "Git control plane이 없어 채택 승인 경계를 세울 수 없다"
    try:
        document = json.load(open(path, encoding="utf-8"))
    except OSError:
        return None, f"승인물이 없다: {path}"
    except (TypeError, ValueError):
        return None, f"승인물이 JSON이 아니다: {path}"
    required = {"schema_version", "baseline_sha256", "target_issues_sha256", "adoptions",
                "payload_sha256", "signature"}
    if not isinstance(document, dict) or set(document) != required \
            or document.get("schema_version") != 1 \
            or not _valid_approval_adoptions(document.get("adoptions")) \
            or not all(isinstance(document.get(key), str) and document[key]
                       for key in ("baseline_sha256", "target_issues_sha256",
                                   "payload_sha256", "signature")):
        return None, f"승인물 형식이 잘못됐다: {path}"
    payload = _approval_payload(document["baseline_sha256"], document["target_issues_sha256"],
                                document["adoptions"])
    if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), document["payload_sha256"]):
        return None, "승인물 payload hash가 맞지 않는다"
    try:
        key = open(SIGNING_KEY(), "rb").read()
    except OSError:
        return None, "승인물 서명 키를 읽을 수 없다"
    signature = hmac.new(key, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, document["signature"]):
        return None, "승인물 서명이 맞지 않는다"
    if not hmac.compare_digest(document["baseline_sha256"], _file_sha256(BASELINE)):
        return None, "승인물이 현재 baseline에 결속되지 않았다"
    if not hmac.compare_digest(document["target_issues_sha256"], _issues_sha256(cur)):
        return None, "승인물이 현재 이슈 집합에 결속되지 않았다"
    requested = [f"{row['checker']}:{row['issue_id']}" for row in document["adoptions"]]
    return _resolve_adoptions(requested, new_issues)


def cmd_approve_adoption(adopt_qualified_ids=()):
    """Write the dispatcher approval under .git, outside fresh-worker write authority."""
    if not _root_ok():
        print(f"승인 root 불일치: M.ROOT={M.ROOT} vs 도구 위치={SELF_ROOT}", file=sys.stderr)
        return 1
    if not os.path.exists(SIGNING_KEY()):
        print("승인할 수 없다: baseline이 봉인되지 않았다")
        return 1
    base, state = _load_baseline()
    if state != "ok":
        print(f"승인할 수 없다: baseline {state}")
        return 1
    cur = measure()
    dead = [checker for checker, issue_ids in cur.items() if issue_ids is None]
    if dead:
        print(f"승인할 수 없다: 검사기 실패: {', '.join(dead)}")
        return 1
    new_issues = {checker: sorted(cur[checker] - base.get(checker, set()))
                  for checker in cur}
    new_issues = {checker: issue_ids for checker, issue_ids in new_issues.items() if issue_ids}
    adopted, error = _resolve_adoptions(adopt_qualified_ids, new_issues)
    if error:
        print("승인할 수 없다: " + error)
        return 1
    effective_base = {checker: set(issue_ids) for checker, issue_ids in base.items()}
    for checker, issue_id in adopted:
        effective_base.setdefault(checker, set()).add(issue_id)
    reason, _advance = _verdict(cur, effective_base, "ok")
    if reason:
        print("승인할 수 없다: " + reason)
        return 1
    approval = _approval_document(cur, adopted)
    path = APPROVAL()
    if path is None:
        print("승인할 수 없다: Git control plane이 없다")
        return 1
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as output:
            json.dump(approval, output, ensure_ascii=False, indent=0)
        os.replace(tmp, path)
    except OSError as error:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        print(f"승인물을 쓸 수 없다: {path}: {error}")
        return 1
    print("채택 승인 저장: " + ", ".join(f"{checker}:{issue_id}"
                                         for checker, issue_id in adopted))
    return 0


def _cmd_baseline_locked():
    # A sealed installation may not silently replace its baseline while an index change is staged.
    # This is the setup --force bypass: a failed setup used to adopt the broken staged tree first.
    staged = subprocess.run(["git", "-C", M.ROOT, "diff", "--cached", "--quiet", "--"],
                            capture_output=True)
    unstaged = subprocess.run(["git", "-C", M.ROOT, "diff", "--quiet", "--"],
                              capture_output=True)
    if os.path.exists(SIGNING_KEY()) and (staged.returncode != 0 or unstaged.returncode != 0):
        print("기준선을 못 세운다 — sealed 설치의 tracked tree가 clean하지 않다")
        return 1
    cur = measure()
    dead = [k for k, v in cur.items() if v is None]
    if dead:
        print(f"기준선을 못 세운다 — 검사기 실패: {', '.join(dead)}")
        return 1
    adopted = []
    if os.path.exists(SIGNING_KEY()):
        base, state = _load_baseline()
        if state == "corrupt":
            print("기준선을 못 세운다 — sealed baseline이 손상됐다")
            return 1
        if state == "absent":
            pass
        else:
            new_issues = {checker: sorted(cur[checker] - base.get(checker, set()))
                          for checker in cur}
            new_issues = {checker: ids for checker, ids in new_issues.items() if ids}
            if new_issues:
                adopted, adoption_error = _load_adoption_approval(cur, new_issues)
                if adoption_error:
                    print("기준선을 못 세운다 — " + adoption_error)
                    return 1
            effective_base = {checker: set(issue_ids) for checker, issue_ids in base.items()}
            for checker, issue_id in adopted:
                effective_base.setdefault(checker, set()).add(issue_id)
            reason, _advance = _verdict(cur, effective_base, "ok")
            if reason:
                print("기준선을 못 세운다 — " + reason)
                return 1
    _save_baseline(cur, adopted)
    for p in (PENDING(),):
        with contextlib.suppress(OSError):
            os.remove(p)
    suffix = (" · adopted " + ", ".join(issue_id for _checker, issue_id in adopted)
              if adopted else "")
    print("기준선 저장: " + " · ".join(f"{k} {len(v)}건" for k, v in cur.items()) + suffix)
    return 0


def cmd_baseline():
    if not _root_ok():
        print(f"실행 root 불일치: M.ROOT={M.ROOT} vs 도구 위치={SELF_ROOT}", file=sys.stderr)
        return 1
    with _lock() as got:
        if not got:
            print("기준선을 못 세운다: gate lock을 얻지 못했다")
            return 1
        return _cmd_baseline_locked()


def cmd_seal_baseline():
    """Upgrade a measured legacy baseline to an HMAC-sealed document during hook repair."""
    if not _root_ok():
        print("baseline seal root 불일치", file=sys.stderr)
        return 1
    base, state = _load_baseline()
    if state != "ok":
        print(f"baseline seal 거부: baseline {state}", file=sys.stderr)
        return 1
    key_path = SIGNING_KEY()
    if not os.path.exists(key_path):
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as key_file:
            key_file.write(secrets.token_bytes(32))
    _save_baseline(base)
    print("baseline sealed: sha256+hmac")
    return 0


def cmd_status():
    base, state = _load_baseline()
    cur = measure()
    print(f"root      : {M.ROOT}" + ("" if _root_ok() else f"  (!! 도구 위치 {SELF_ROOT}와 불일치)"))
    print(f"dirty     : {os.path.exists(DIRTY())}  ({DIRTY()})")
    print(f"pending   : {os.path.exists(PENDING())}")
    print(f"기준선    : {state} — " + " · ".join(f"{k} {len(v)}건" for k, v in base.items()))
    print("현재      : " + " · ".join(
        f"{k} {'측정실패' if v is None else str(len(v)) + '건'}" for k, v in cur.items()))
    for k, v in cur.items():
        for i in sorted(v or [])[:10]:
            print(f"  {k}  {i}")
    return 0


def cmd_check():
    """Stop 훅. dirty이거나 미해결 실패(pending)가 있으면 검사한다."""
    try:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:
            payload = {}
        if not _root_ok():
            return _block(t("gate.root_block", root=M.ROOT, tool=SELF_ROOT))
        if not (os.path.exists(DIRTY()) or os.path.exists(PENDING())):
            return 0

        with _lock() as got:
            if not got:
                return _block(t("gate.lock_block"))
            token = _read(DIRTY())
            base, state = _load_baseline()
            cur = measure()
            # 검사 도중 새 편집이 들어왔으면 마커를 지우지 않는다 (lost wakeup 차단).
            moved = _read(DIRTY()) != token
            reason, advance = _verdict(cur, base, state)
            if advance and not moved:
                _save_baseline(cur)
            if reason:
                # **막은 뒤에도 재검증이 남아야 한다.** 마커만 지우면 다음 Stop이 조용히 통과했다.
                _mark(PENDING())
                if not moved:
                    with contextlib.suppress(OSError):
                        os.remove(DIRTY())
                M.log_run("gate", "blocked@Stop")
                return _block(reason)
            if not moved:
                for p in (DIRTY(), PENDING()):
                    with contextlib.suppress(OSError):
                        os.remove(p)
            M.log_run("gate", "pass@Stop", ok=True)
            return 0
    except Exception as e:
        # 게이트 자신의 예외는 측정 실패다. 조용히 0을 내면 후방선이 fail-open이 된다
        # (2026-09-17 독립 감사 K: measure()가 터져도 무출력 성공). pending을 남겨 다음 턴이 회수한다.
        with contextlib.suppress(Exception):
            _mark(PENDING())
        with contextlib.suppress(Exception):
            M.log_run("gate", f"error@Stop:{type(e).__name__}")
        return _block(t("gate.self_failed", error_type=type(e).__name__))


def _read(p):
    try:
        return open(p).read()
    except OSError:
        return None


def cmd_resume():
    """UserPromptSubmit 훅. interrupt로 Stop이 안 돈 턴과, 막혔는데 안 고쳐진 상태를 회수한다.

    막지 않고 알린다 — 사용자가 방금 새 지시를 넣은 순간에 차단하면 성가시기만 하다."""
    try:
        if not _root_ok():
            return 0
        if not (os.path.exists(DIRTY()) or os.path.exists(PENDING())):
            return 0
        with _lock(timeout=30) as got:
            if not got:
                return 0
            token = _read(DIRTY())
            base, state = _load_baseline()
            cur = measure()
            moved = _read(DIRTY()) != token
            reason, advance = _verdict(cur, base, state)
            if advance and not moved:
                _save_baseline(cur)
            if reason:
                _mark(PENDING())
                if not moved:
                    with contextlib.suppress(OSError):
                        os.remove(DIRTY())
                M.log_run("gate", "resume-warn")
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": t("gate.resume_failed", reason=reason)}},
                    ensure_ascii=False))
                return 0
            if not moved:
                for p in (DIRTY(), PENDING()):
                    with contextlib.suppress(OSError):
                        os.remove(p)
            return 0
    except Exception as e:
        # 막지는 않되 침묵하지 않는다. pending을 유지해 다음 Stop이 다시 검사하게 한다 (독립 감사 K).
        with contextlib.suppress(Exception):
            _mark(PENDING())
        with contextlib.suppress(Exception):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": t("gate.resume_self_failed", error_type=type(e).__name__)}},
                ensure_ascii=False))
        return 0


def _staged_tools_compile(tmp):
    """index에 올라간 파이썬 도구가 문법적으로 성립하는가.

    안 보면 이 구멍이 난다 (codex 라운드 4): 검사기를 깨진 채로 stage하고 worktree만
    되돌리면, 훅은 worktree 검사기로 index 문서를 검사해서 통과시킨다."""
    import py_compile
    bad = []
    ls = subprocess.run(["git", "-C", M.ROOT, "ls-files", "--cached", "tools/*.py"],
                        capture_output=True, text=True).stdout.split()
    for rel in ls:
        p = os.path.join(tmp, rel)
        if not os.path.exists(p):
            continue
        try:
            py_compile.compile(p, cfile=os.path.join(tmp, ".pyc-scratch"), doraise=True)
        except Exception as e:
            bad.append(f"{rel}: {type(e).__name__}")
    return bad


def _staged_markdown_paths():
    """Read staged Markdown paths without Git's quotePath transformation."""
    listed = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", M.ROOT,
         "ls-files", "-z", "--cached", "*.md"], capture_output=True,
    )
    if listed.returncode != 0 or (listed.stdout and not listed.stdout.endswith(b"\0")):
        raise ValueError("staged Markdown file list measurement failed")
    try:
        paths = [p.decode("utf-8") for p in listed.stdout.split(b"\0") if p]
    except UnicodeDecodeError as error:
        raise ValueError("staged Markdown path is not UTF-8") from error
    if any("\n" in path or "\r" in path for path in paths):
        raise ValueError("newline in staged Markdown path")
    return paths


def cmd_precommit():
    """pre-commit 훅. 커밋되는 index를 검사하고, 조금이라도 못 미더우면 막는다 (fail closed)."""
    if not _root_ok():
        print(f"[gate] 실행 root 불일치 ({M.ROOT} vs {SELF_ROOT}). 커밋을 막는다.", file=sys.stderr)
        return 1
    tmp = tempfile.mkdtemp(prefix="mottori-gate-")
    try:
        r = subprocess.run(["git", "-C", M.ROOT, "checkout-index", "-a", "--prefix", tmp + "/"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[gate] index를 꺼내지 못했다: {r.stderr.strip()[:200]}", file=sys.stderr)
            return 1
        if not _ensure_git_tree(tmp):
            print("[gate] index 임시 트리에 Git metadata를 만들지 못했다", file=sys.stderr)
            return 1
        bad = _staged_tools_compile(tmp)
        if bad:
            print("[gate] index의 파이썬 도구가 깨져 있다: " + ", ".join(bad), file=sys.stderr)
            print("  검사기가 깨진 채 커밋되면 이 게이트 자체가 무력해진다.", file=sys.stderr)
            return 1
        enforce_cmd = [sys.executable, os.path.join(HERE, "enforce.py"),
                       "--issues", "--index", "--root", M.ROOT]
        absolute_issues = _issues(enforce_cmd, cwd=M.ROOT)
        if absolute_issues is None:
            print("[gate] staged privacy enforcement를 측정하지 못했다", file=sys.stderr)
            return 1
        if absolute_issues:
            print("[gate] absolute staged violation: "
                  + "; ".join(sorted(absolute_issues)[:8]), file=sys.stderr)
            return 1
        fl = os.path.join(tmp, ".gate-filelist")
        try:
            paths = _staged_markdown_paths()
        except ValueError as error:
            print(f"[gate] {error}", file=sys.stderr)
            return 1
        with open(fl, "w", encoding="utf-8") as filelist:
            filelist.write("".join(path + "\n" for path in paths))

        base, state = _load_baseline()
        cur = measure(tree=tmp, filelist=fl)
        reason, _ = _verdict(cur, base, state)
        if reason:
            print("[gate] " + reason, file=sys.stderr)
            return 1
        M.log_run("gate", "precommit-pass", ok=True)
        return 0
    except Exception as e:
        print(f"[gate] 게이트 자신이 실패했다: {e}. 커밋을 막는다.", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _gated_issue_ids(measured):
    """Checker-qualified gated IDs make cross-mode sets directly comparable."""
    return sorted(
        f"{checker}:{ident}"
        for checker, issues in measured.items()
        for ident in (issues or set())
    )


def cmd_selfcheck():
    """Compare live direct measurement with the measurement used by precommit."""
    if not _root_ok():
        print(f"selfcheck: FAIL root mismatch ({M.ROOT} vs {SELF_ROOT})")
        return 1
    tmp = tempfile.mkdtemp(prefix="mottori-gate-selfcheck-")
    try:
        extracted = subprocess.run(
            ["git", "-C", M.ROOT, "checkout-index", "-a", "--prefix", tmp + "/"],
            capture_output=True, text=True,
        )
        if extracted.returncode != 0:
            print("selfcheck: FAIL could not extract the index")
            return 1
        bad = _staged_tools_compile(tmp)
        if bad:
            print("selfcheck: FAIL staged Python is invalid: " + ", ".join(bad))
            return 1
        try:
            paths = _staged_markdown_paths()
        except ValueError as error:
            print(f"selfcheck: FAIL {error}")
            return 1
        filelist = os.path.join(tmp, ".gate-filelist")
        with open(filelist, "w", encoding="utf-8") as output:
            output.write("".join(path + "\n" for path in paths))

        direct = measure()
        precommit = measure(tree=tmp, filelist=filelist)
        dead_direct = sorted(name for name, value in direct.items() if value is None)
        dead_precommit = sorted(name for name, value in precommit.items() if value is None)
        if dead_direct or dead_precommit:
            print("selfcheck: FAIL checker measurement unavailable")
            print("  direct-dead=" + json.dumps(dead_direct, ensure_ascii=False))
            print("  precommit-dead=" + json.dumps(dead_precommit, ensure_ascii=False))
            return 1

        direct_ids = _gated_issue_ids(direct)
        precommit_ids = _gated_issue_ids(precommit)
        if direct_ids != precommit_ids:
            print("selfcheck: WARN direct/precommit gated issue ID sets differ")
            print("  direct=" + json.dumps(direct_ids, ensure_ascii=False))
            print("  precommit=" + json.dumps(precommit_ids, ensure_ascii=False))
        else:
            print(f"selfcheck: PASS gated issue ID sets match ({len(direct_ids)})")
        return 0
    except Exception as error:
        print(f"selfcheck: FAIL {type(error).__name__}: {error}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "baseline":
        if len(sys.argv) != 2:
            print("사용: gate.py baseline", file=sys.stderr)
            return 2
        return cmd_baseline()
    if cmd == "approve-adoption":
        requested = []
        args = sys.argv[2:]
        while args:
            if len(args) < 2 or args[0] != "--adopt" or not args[1]:
                print("사용: gate.py approve-adoption --adopt <checker:issue-id> ...",
                      file=sys.stderr)
                return 2
            requested.append(args[1])
            args = args[2:]
        if not requested:
            print("사용: gate.py approve-adoption --adopt <checker:issue-id> ...",
                  file=sys.stderr)
            return 2
        return cmd_approve_adoption(requested)
    return {"dirty": cmd_dirty, "check": cmd_check, "resume": cmd_resume,
            "precommit": cmd_precommit,
            "seal-baseline": cmd_seal_baseline,
            "status": cmd_status, "selfcheck": cmd_selfcheck}.get(cmd, cmd_status)()


if __name__ == "__main__":
    sys.exit(main())
