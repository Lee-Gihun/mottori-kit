#!/usr/bin/env python3
"""Schedules, lists and removes the loop's jobs on this Mac through launchd: one job file per label in
the user's LaunchAgents folder, made from the template system/loop/launchd/job.plist.

A job is a dict: label, argv (the program and its arguments), root (the working folder), when
({"weekday": 0-6 with 0 Sunday, "hour", "minute"}; no weekday means every day) and log (the file its
output goes to). Every function returns data; none prints."""
import os
import subprocess
from xml.sax.saxutils import escape

TEMPLATE = os.path.join("system", "loop", "launchd", "job.plist")


def _domain():
    return f"gui/{os.getuid()}"


def agents_dir():
    """Where launchd reads the user's job files."""
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")


def job_file(label):
    return os.path.join(agents_dir(), label + ".plist")


def installed(label):
    """Whether the job file of label is in place: the job was scheduled and not removed."""
    return os.path.isfile(job_file(label))


def loaded_labels():
    """The labels launchd has loaded for this user. Raises RuntimeError when launchctl cannot tell."""
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"launchctl list failed: {e}") from e
    if r.returncode:
        raise RuntimeError(f"launchctl list exit {r.returncode}: {r.stderr.strip()[-160:]}")
    return {cols[-1] for cols in (line.split() for line in r.stdout.splitlines()) if cols}


def loaded(label):
    """Whether launchd has the job of label loaded."""
    r = subprocess.run(["launchctl", "print", f"{_domain()}/{label}"], capture_output=True, text=True, timeout=20)
    return r.returncode == 0


def render(job, template_text):
    """The job file's text for job from the template's text."""
    when = job["when"]
    parts = ([f"<key>Weekday</key><integer>{int(when['weekday'])}</integer>"] if when.get("weekday") is not None else [])
    parts += [f"<key>Hour</key><integer>{int(when['hour'])}</integer>",
              f"<key>Minute</key><integer>{int(when['minute'])}</integer>"]
    values = {"__LABEL__": job["label"], "__ROOT__": job["root"], "__LOG__": job["log"],
              "__HOME__": os.path.expanduser("~")}
    text = template_text.replace("__PROGRAM__", "".join(f"<string>{escape(a)}</string>" for a in job["argv"]))
    text = text.replace("__WHEN__", "".join(parts))
    for key, value in values.items():
        text = text.replace(key, escape(value))
    return text


def install(job):
    """Write the job file and load it, replacing a loaded job of the same label. Returns None when
    done, else the reason it was not."""
    with open(os.path.join(job["root"], TEMPLATE), encoding="utf-8") as f:
        text = render(job, f.read())
    os.makedirs(agents_dir(), exist_ok=True)
    os.makedirs(os.path.dirname(job["log"]), exist_ok=True)
    with open(job_file(job["label"]), "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{job['label']}"], capture_output=True, timeout=20)
    r = subprocess.run(["launchctl", "bootstrap", _domain(), job_file(job["label"])], capture_output=True,
                       text=True, timeout=20)
    return None if r.returncode == 0 else (r.stderr.strip()[-200:] or f"launchctl bootstrap exit {r.returncode}")


def remove(label):
    """Unload the job and delete its file. Returns None when done, else the reason it was not."""
    r = subprocess.run(["launchctl", "bootout", f"{_domain()}/{label}"], capture_output=True, text=True, timeout=20)
    try:
        os.unlink(job_file(label))
    except FileNotFoundError:
        pass
    # bootout of a job that was not loaded fails; with the file gone the job is removed all the same.
    if r.returncode and loaded(label):
        return r.stderr.strip()[-200:] or f"launchctl bootout exit {r.returncode}"
    return None
