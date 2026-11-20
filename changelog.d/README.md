# changelog.d

One unreleased changelog entry per file, so two pull requests adding entries never touch the same
line of the same file and never conflict. `CHANGELOG.md` holds released history; the files here are
what the next version adds to it.

When `library_version` is bumped (`make version/patch`, `make version/minor`, `make version/major`,
`make version/set`, or the Version Bump workflows), `scripts/changelog.py roll` folds these files into the new version
section and deletes them, in the same commit as the bump.

## Adding an entry

Create `<type>-<slug>.md`, where `<type>` is one of `added`, `changed`, `deprecated`, `removed`,
`fixed`, or `security`, and `<slug>` is a few lowercase words joined by hyphens:

```text
changelog.d/fixed-script-none-float-knob.md
```

The file holds the bullet exactly as it should read in `CHANGELOG.md`, and nothing else:

```markdown
- Nuke Script runs when an exposed float knob receives `None` from an upstream node, and keeps
  the knob value saved in the script.
  [#181](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/181)
```

`make check/changelog` enforces the shape:

- the filename names one of the six change types
- nothing else lives here: every file is an entry, named `<type>-<slug>.md`
- the file starts with `- ` and holds exactly one entry
- the file is UTF-8 text
- continuation lines are indented two spaces
- no headings, since the type is in the filename
- `## [Unreleased]` in `CHANGELOG.md` carries no entries of its own; they all live here
- these files fold into a `CHANGELOG.md` that still parses

Wrap at about 100 characters. Nothing checks that, and nothing reformats it either.

What belongs in an entry, and how to word it, is in [CLAUDE.md](../CLAUDE.md#changelog) and
[CONTRIBUTING.md](../CONTRIBUTING.md#changelog).
Refactors, tests, CI, and docs-only changes get no entry at all.

## Previewing what the next version will say

```shell
make changelog
```

That prints the `[Unreleased]` section as the next version will show it: these files folded in,
change types in Keep a Changelog order, breaking changes first within each type.
