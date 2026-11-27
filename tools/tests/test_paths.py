#!/usr/bin/env python3
import os
import subprocess
import sys


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import paths


PASSED = 0
FAILED = []


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        print("✓ " + name)
    else:
        FAILED.append(name)
        print("✗ " + name + (": " + detail if detail else ""))


def test_instance_root_spellings():
    # Every tool takes its root from here, so each spelling must land on one folder.
    saved = os.environ.get("MOTTORI_INSTANCE")
    try:
        for value, want in (("", ROOT), ("~", os.path.expanduser("~")),
                            ("rel", os.path.join(os.getcwd(), "rel"))):
            os.environ["MOTTORI_INSTANCE"] = value
            check(f"instance root for {value!r}", paths.instance_root() == want, paths.instance_root())
        os.environ.pop("MOTTORI_INSTANCE")
        check("unset instance root is the folder above tools/", paths.instance_root() == ROOT)
    finally:
        if saved is None:
            os.environ.pop("MOTTORI_INSTANCE", None)
        else:
            os.environ["MOTTORI_INSTANCE"] = saved


def test_import_has_no_side_effects():
    # Importing paths alone prints nothing and loads no other module of the kit.
    probe = ("import sys, os; sys.path.insert(0, 'tools/lib'); before = set(sys.modules); import paths; "
             "kit = {os.path.splitext(n)[0] for d in ('tools', 'tools/lib') for n in os.listdir(d) if n.endswith('.py')}; "
             "print(sorted((set(sys.modules) - before) & (kit - {'paths'})))")
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True)
    check("import paths loads no kit module and prints nothing else",
          result.returncode == 0 and result.stdout == "[]\n" and not result.stderr,
          result.stdout + result.stderr)


if __name__ == "__main__":
    test_instance_root_spellings()
    test_import_has_no_side_effects()
    total = PASSED + len(FAILED)
    print(f"paths: {PASSED}/{total} passed")
    sys.exit(0 if not FAILED else 1)
