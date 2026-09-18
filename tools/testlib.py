#!/usr/bin/env python3
"""Shared execution-evidence helper for the repository's regression suites."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable, TypeVar


T = TypeVar("T")
TEST_LOG_ENV = "MOTTORI_TEST_LOG"
TEST_RUN_ID_ENV = "MOTTORI_TEST_RUN_ID"
RUN_ID_RE = re.compile(r"[A-Za-z0-9._+-]{1,128}")


def test_id(source_file: str, test: Callable[..., object]) -> str:
    """Return the stable marker ID used by evidencecheck."""
    source = Path(source_file).resolve()
    try:
        rel = source.relative_to(Path(__file__).resolve().parent.parent).as_posix()
    except ValueError:
        rel = f"tools/{source.name}"
    return f"{rel}::{test.__name__}"


def record_test(source_file: str, test: Callable[..., object]) -> None:
    """Append one machine-readable execution record when a log was requested."""
    raw = os.environ.get(TEST_LOG_ENV)
    if not raw:
        return
    run_id = os.environ.get(TEST_RUN_ID_ENV, "")
    if not RUN_ID_RE.fullmatch(run_id):
        return
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"RAN {run_id} {time.time_ns()} {test_id(source_file, test)}\n".encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def run_test(test: Callable[..., T], source_file: str, *args: object, **kwargs: object) -> T:
    """Record a test at its invocation boundary, then execute it."""
    record_test(source_file, test)
    return test(*args, **kwargs)
