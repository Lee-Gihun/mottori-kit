# Instance rules: CHANGEME

*This file is not committed because `.gitignore` excludes it. Write only facts specific to this machine here.*
*Always-on core rule 1 in `AGENTS.md`, Do not touch frozen areas, points to this document.*

Written: CHANGEME · context: CHANGEME

---

## 1. Frozen areas: read only; do not reorganize, delete, or add

Agents do not modify paths listed here.

- Example: `evidence/`, submission evidence whose original form is valuable and would be damaged by reconstruction
- Example: `archive/`, completed records
- CHANGEME

*If there are none yet, write "none yet". A blank section cannot distinguish unwritten from absent.*

## 2. Data boundary: what is inside and what is outside

The Data boundary section of `system/rituals.md` gives three principles. Specify **this instance's direction** here.

**Imports (outside to here).** What does a person bring in directly?
- CHANGEME

**Landing point.** Where do imports go? There must be one place.
- Example: `_private/work/`, readable and searchable within a session but never committed, quoted, or sent externally
- CHANGEME

**What must never leave (here to outside).** This applies to every remote, cloud, and artifact.
- CHANGEME

**Export path.** How may permitted material leave, such as by a person, copy and paste, or a named channel?
- CHANGEME

## 3. Remote policy

`instance.remote_allowlist` in `system/memory-config.json` is the mechanical enforcement point.
The valve check in `python3 tools/doctor.py` verifies it each time.

- Allowed remotes for this instance: CHANGEME (if none, write "none; do not configure a remote")
- Backup method: CHANGEME
  *(Without a remote, this repository is not backed up. Arrange a separate backup.)*

## 4. Constraints specific to this machine

- Example: company policy forbids screen recording, meeting recording, or external API calls
- Example: software that cannot be installed
- CHANGEME

## 5. Tracks

The `tracks` array in `system/memory-config.json` is authoritative. Record only one line explaining why each
track exists.

- CHANGEME
