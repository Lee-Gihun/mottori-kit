# Projects

One folder per project: a piece of work with its own purpose, such as a paper, a product launch, a course you
teach or a side project. Its documents go in its folder, and so do scripts and small code. A repository of its
own, or a folder another program writes to, stays where it is: name it under `outside` and the agent is told
where it is.

Every folder here is a project, named after the folder, so a folder of notes you bring in as it is counts as one.
A folder whose name starts with `.` or `_` is left out. To give a project a name, an area, a status or folders
outside this one, start its `README.md` with a block like this. Every line is optional; delete the ones you do
not need:

```text
---
name: The project's name
area: A word that groups related projects in the map below
status: active
canonical: README.md
outside:
  - ~/code/app: the app's own repository
private:
  - _private/the-project/: what Git must never take
---
```

`status` is `active`, `paused`, `planned` or `closed`. A project that ends keeps its folder; only its status
changes. `canonical` is the file to open first, inside the project's folder. `private` paths start with
`_private/`, and `outside` paths can be anywhere. Doctor warns about what the block names but cannot find, such
as an outside folder that is on another machine; nothing here makes it fail. A README that starts with a block of
another kind, such as a site generator's `title` and `tags`, is left as it is and not read.

The status board and the dossier list are separate: they show only what `tracks` and `threads` in
`instance/config.json` name.

Git ignores this folder until you keep it: add `!/projects/` below the marker at the end of `.gitignore`
for a private remote of yours (MANUAL.md, "Where things are").

The table below is redrawn from the folders whenever the state page (`state/NOW.md`) is, which happens at session
start and at the end of a turn, and by `python3 tools/projects.py draw`. Do not edit it by hand; write your own
notes above or below the two marker lines.

<!-- projects:start -->
<!-- projects:end -->
