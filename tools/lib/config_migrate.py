#!/usr/bin/env python3
"""Write the instance configuration at setup: the template merged with an existing config and
migrated to the current schema.

Every check runs before anything is written, and a refusal changes nothing. config.py reads and
validates the file this writes.

Command line (setup.sh uses it):
  python3 tools/lib/config_migrate.py NAME
      Write the merged and migrated config from templates/; the journal rows setup read with
      `python3 tools/lib/journal.py rows` arrive on stdin as JSON."""
import datetime
import json
import os
import shutil
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [p for p in (TOOLS, os.path.join(TOOLS, "lib")) if p not in sys.path]
import config as C  # noqa: E402
import paths  # noqa: E402
import safeio  # noqa: E402


def carry_over(template, prior):
    """Return prior values with template keys that prior lacks filled in.

    Instance settings (egress deny prefixes, thresholds) are owned by the
    instance; resetting them to the template on --force silently widens what is sent to
    models. Template-owned documentation keys ("_" prefix) still follow the template.
    """
    if not (isinstance(template, dict) and isinstance(prior, dict)):
        return prior
    out = dict(prior)
    for key, value in template.items():
        if key.startswith("_") or key not in prior:
            out[key] = value
        else:
            out[key] = carry_over(value, prior[key])
    return out


def reset_paths(prior, merged, prefix=""):
    """List dotted keys whose prior value did not survive the merge, so a reset is never silent."""
    out = []
    for key, value in prior.items() if isinstance(prior, dict) else ():
        if key.startswith("_"):
            continue
        dotted = prefix + key
        if not isinstance(merged, dict) or key not in merged:
            out.append(dotted)
        elif isinstance(value, dict):
            out.extend(reset_paths(value, merged[key], dotted + "."))
        elif isinstance(value, list) and isinstance(merged[key], list):
            if any(item not in merged[key] for item in value):
                out.append(dotted)
        elif value != merged[key]:
            out.append(dotted)
    return out


def legacy_watermark(rows, journal_types):
    """Return the newest time among the journal rows that existed before the migration.

    rows are (type, time, source) as `journal.py rows` prints them. The cutoff is the newest
    existing row, not the migration time: kept to the second, the migration time would also cover
    the setup event logged in that same second. A row whose type the new schema lacks, or whose
    time has no zone, stops the migration instead of guessing a cutoff."""
    latest = None
    for row_type, ts, source in rows:
        if row_type not in journal_types:
            raise ValueError(f"legacy journal type is absent from the new schema: {source}")
        stamp = C.parse_timestamp(ts)
        if stamp is None:
            raise ValueError(f"legacy journal timezone missing: {source}")
        latest = stamp if latest is None or stamp > latest else latest
    return latest.isoformat(timespec="seconds") if latest else None


def _merge(template, old):
    """Start from the old config, add only the template keys it lacks, and take the schema
    version, the visibility block and (for an older schema) the journal types from the template."""
    cfg = carry_over(template, old)
    cfg["schema_version"] = template["schema_version"]
    cfg["journal_visibility"] = json.loads(json.dumps(template["journal_visibility"]))
    old_types = old.get("journal_types", [])
    if old.get("schema_version", 1) == template["schema_version"] and isinstance(old_types, list):
        # A current-schema instance keeps its own journal types next to any new template types.
        # Older schemas are rewritten to the template vocabulary, and legacy_watermark() stops
        # the migration when an existing row uses a type that vocabulary no longer has.
        cfg["journal_types"] = list(dict.fromkeys(template["journal_types"] + old_types))
    else:
        cfg["journal_types"] = template["journal_types"]
    return cfg


def _migrate_visibility(cfg, old, rows):
    """Fill the visibility cutover: kept from schema 4, frozen at the newest row before that."""
    vis = cfg["journal_visibility"]
    old_schema = old.get("schema_version", 1)
    if old_schema > cfg["schema_version"]:
        raise ValueError(f"existing config v{old_schema} is newer than this engine v{cfg['schema_version']}")
    # A config from before v0.10 is not migrated (KIT-DR-086): nothing records an installation
    # that has one. Moved aside, it leaves a folder with a journal and no config, which the branch
    # below migrate() handles: the rows written before it stay private.
    if old_schema < 4:
        raise ValueError(OLD_SCHEMA.format(schema=old_schema))
    old_vis = old.get("journal_visibility")
    if old_vis is not None:
        # The validator guarantees the timezone and track types. An installation that keeps no list
        # (null) keeps none; one that holds a list keeps its list, whoever wrote it (KIT-DR-071 (3)).
        kept = old_vis["public_tracks"]
        vis["public_tracks"] = None if kept is None else list(dict.fromkeys(kept))
        vis["legacy_cutoff"] = old_vis.get("legacy_cutoff")
        vis["legacy_public_tracks"] = list(dict.fromkeys(old_vis.get("legacy_public_tracks") or []))


OLD_SCHEMA = ("existing config is schema v{schema}, from before v0.10, which setup no longer moves; move it "
              "aside (mv instance/config.json instance/config.json.old) and run bash setup.sh again: it "
              "writes a new config, and your journal and documents stay")


def migrate(name, rows, root=None):
    """Write the instance configuration from the template, keeping an existing one's settings.

    Every check runs before the backup and the write; a refusal is a ValueError and changes
    nothing. Return the lines setup prints."""
    root = root or paths.instance_root()
    dst = paths.config_file(root)
    with open(paths.config_template(root), encoding="utf-8") as f:
        cfg = json.load(f)
    old, had_old = {}, os.path.exists(dst)
    if had_old:
        try:
            with open(dst, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            raise ValueError(f"existing config parse failed; original will not be overwritten: {e}")
        C.validate(old)
        cfg = _merge(cfg, old)
    cfg["tracks"] = old.get("tracks", [])
    cfg["threads"] = old.get("threads", [])
    if old.get("checks"):
        cfg["checks"] = old["checks"]
    if old.get("personal_pointer"):
        cfg["personal_pointer"] = old["personal_pointer"]
    if had_old:
        _migrate_visibility(cfg, old, rows)
    else:
        # Leftover history without a config has no record of what was public: freeze it private. The
        # combined view still shows it; only the public page does not.
        watermark = legacy_watermark(rows, cfg["journal_types"])
        if watermark:
            cfg["journal_visibility"]["legacy_cutoff"] = watermark
            cfg["journal_visibility"]["legacy_public_tracks"] = []
    cfg["instance"]["name"] = name
    # An earlier version kept a work or personal context and a list of remotes a folder might push
    # to. Nothing reads them now, so a config that carries them loses them here.
    dropped = [key for key in ("context", "remote_allowlist") if cfg["instance"].pop(key, None) is not None]
    # An older setup recorded the language of the starter documents here; nothing reads it now.
    cfg["instance"].pop("lang", None)
    C.validate(cfg)
    backup = _backup(dst, root) if had_old else None
    # A session reading the config during this write must see the old file or the new one, never a part.
    safeio.atomic_write(dst, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    shown = os.path.relpath(dst, root)
    lines = [f"  {shown}  ({name})"]
    if had_old:
        lines.append(f"     preserved: tracks {len(cfg['tracks'])} · threads {len(cfg['threads'])} · backup {backup}")
        # instance.name comes from this run, and context, remote_allowlist and lang are dropped on
        # purpose, so none of them is a reset.
        reset = [p for p in reset_paths(old, cfg)
                 if p not in ("schema_version", "instance.name", "instance.context", "instance.lang",
                              "instance.remote_allowlist")
                 and not p.startswith("journal_visibility")]
        if reset:
            lines.append(f"     reset to the template: {', '.join(reset)}")
    if dropped:
        lines.append("     no longer used and removed: " + ", ".join("instance." + key for key in dropped)
                     + " (the kit no longer refuses commits or pushes by context or by remote)")
    return lines


def _backup(dst, root):
    """Copy the old config under a new name each run, so a later --force never overwrites it.

    Return the copy's path relative to root."""
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = f"{dst}.bak-{stamp}"
    n = 1
    while os.path.exists(backup):
        backup = f"{dst}.bak-{stamp}-{n}"
        n += 1
    shutil.copy2(dst, backup)
    return os.path.relpath(backup, root)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["-h"], ["--help"]):
        print(__doc__)
        return 0
    if len(argv) != 1:
        print(__doc__.split("Command line", 1)[1].split("\n", 1)[1].rstrip(), file=sys.stderr)
        return 2
    try:
        lines = migrate(*argv, rows=json.load(sys.stdin))
    except ValueError as e:
        # A refusal is one line naming its reason, not a stack trace.
        print(e, file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
