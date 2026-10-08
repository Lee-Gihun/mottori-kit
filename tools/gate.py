#!/usr/bin/env python3
"""Check changed work against a recorded set of known issues.

Checker protocol (--issues): stable-id<TAB>message rows followed by a final #issues N line.
Findings exit zero; failed measurement exits nonzero. Missing or inconsistent trailers fail
closed. IDs prefixed with ~ are advisory time-based findings.

Block newly introduced issues and removed checkers. Tighten the baseline when issues
disappear; only an explicit baseline command may adopt a new set.

Stop hooks cover Write, Edit, and NotebookEdit. Precommit checks the staged tree; resume
reports pending work after missed or interrupted hooks. Local hooks cannot prevent
--no-verify.

Commands: dirty, check, resume, precommit, selfcheck, approve-adoption, baseline, status.
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

# Bind execution to this file's root; an environment override must not redirect validation to a
# clean clone.
SELF_ROOT = os.path.dirname(HERE)

BASELINE = os.path.join(M.STATE, ".gate-baseline.json")

CHECKS = [
    ("linkcheck", [sys.executable, os.path.join(HERE, "linkcheck.py"), "--issues"]),
    ("evidencecheck", [sys.executable, os.path.join(HERE, "evidencecheck.py"), "--issues"]),
    ("now-check", [sys.executable, os.path.join(HERE, "now.py"), "check", "--issues"]),
    # Check generated manifests against the staged tree in kit distributions.
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
    """Return an untracked path for gate state."""
    g = _gitdir()
    return os.path.join(g, name) if g else os.path.join(M.STATE, "." + name)


DIRTY = lambda: _ephem("mottori-gate-dirty")
PENDING = lambda: _ephem("mottori-gate-pending")     # A blocked check remains pending until revalidated.
LOCK = lambda: _ephem("mottori-gate-lock")
SIGNING_KEY = lambda: _ephem("mottori-gate-key")


def _approval_path():
    gitdir = _gitdir()
    return os.path.join(gitdir, "mottori-gate-adoption-approval.json") if gitdir else None


APPROVAL = _approval_path


@contextlib.contextmanager
def _lock(timeout=150):
    """Serialize dirty marking, measurement, and baseline updates so a concurrent edit cannot
    lose its pending marker.
    """
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
    """Return one checker's gated issue IDs, or None when measurement fails."""
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
        return None                      # Findings still exit zero in machine-protocol mode.
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    if not lines or not lines[-1].startswith("#issues "):
        return None                      # The trailer must be the final output line.
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
    # Give the extracted tree its own Git metadata before tests can resolve the parent
    # repository.
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
    """Ensure each cited suite has fresh evidence for the current run ID. Reuse an inherited
    log only when it already covers every required test; otherwise run the cited suites.
    Fixtures needing a real execution use an empty log or a different run ID.
    """
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
            # Use staged checkers and documents; resolve run evidence and instance decisions
            # from the local overlay.
            staged_checker = os.path.join(tree, "tools", "evidencecheck.py")
            c = [sys.executable, staged_checker, "--issues", "--tree", tree,
                 "--local-root", M.ROOT]
        if tree and name == "now-check":
            # Validate staged engine bytes. Installed kits supply ignored config/state through
            # the local overlay.
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
    """Return (issue-set mapping, state), where state is ok, absent, or corrupt."""
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
    """Return (blocking reason or None, whether to tighten the baseline). Never adopt new
    issues.
    """
    dead = sorted(k for k, v in cur.items() if v is None)
    if dead:
        return t("gate.checker_dead", items=", ".join(dead)), False
    if state == "corrupt":
        return t("gate.baseline_corrupt", path=BASELINE), False
    if state == "absent":
        return t("gate.baseline_absent"), False
    only_b = sorted(set(base) - set(cur))
    if only_b:
        # Removing a checker must not erase its findings.
        return t("gate.checks_changed", only_base=t("gate.only_base", items=", ".join(only_b)),
                 only_current=""), False
    # A new checker starts with an empty baseline: all its findings are new, while zero findings
    # can be recorded safely.
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
        # Keep the dirty marker even when the lock cannot be acquired.
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
    # A sealed installation must not replace its baseline while an index change is staged.
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
    """Run the Stop check when dirty or when a previous failure remains pending."""
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
            # Do not clear a marker created by an edit during measurement.
            moved = _read(DIRTY()) != token
            reason, advance = _verdict(cur, base, state)
            if advance and not moved:
                _save_baseline(cur)
            if reason:
                # Keep unresolved failures pending so the next Stop rechecks them.
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
        # Treat gate exceptions as failed measurement and retain pending state.
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
    """Report pending work at UserPromptSubmit without blocking the new instruction.
    Interrupted turns and unresolved failures remain eligible for later Stop checks.
    """
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
        # Report failure without blocking the prompt; keep pending state for the next Stop.
        with contextlib.suppress(Exception):
            _mark(PENDING())
        with contextlib.suppress(Exception):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": t("gate.resume_self_failed", error_type=type(e).__name__)}},
                ensure_ascii=False))
        return 0


def _staged_tools_compile(tmp):
    """Check Python syntax in the staged tree rather than a potentially different worktree
    copy.
    """
    import py_compile
    bad = []
    listed = subprocess.run(
        ["git", "-C", M.ROOT, "ls-files", "-z", "--cached", "tools/*.py"],
        capture_output=True,
    )
    if listed.returncode != 0 or (listed.stdout and not listed.stdout.endswith(b"\0")):
        raise ValueError("staged Python file list measurement failed")
    for raw_path in listed.stdout.split(b"\0"):
        if not raw_path:
            continue
        rel = os.fsdecode(raw_path)
        p = os.path.join(tmp, rel)
        if not os.path.exists(p):
            bad.append(f"{rel}: missing staged file")
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
    """Check the index that will be committed and fail closed when measurement is incomplete."""
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
