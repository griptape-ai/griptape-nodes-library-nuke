# Changelog

All notable changes to the Nuke Nodes Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `griptape-nodes-library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.4.0] - 2026-11-11

### Added

- A refused Nuke host connect reports whether the engine is running a workflow, and which one, so
  the host can warn the artist before taking the engine over.
- `NukeGetCurrentProjectRequest` returns the current project's `project_id`, the same id
  `NukeListProjectsRequest` lists and `NukeSetCurrentProjectRequest` accepts.
- `NukePingRequest` lets a Nuke host check that the engine itself is alive.
- Describe reports `file_format` on a parameter whose value names a file format (`image`, `video`,
  `audio`, `threed`), so a host can drop format choices it cannot open and leave other dropdowns
  alone.
- A connected Nuke host is listed on the engine's session under its `client_name`, so engine
  discovery shows which engine a Nuke session is driving. A clean disconnect or a forced takeover
  delists the previous host.
  [#163](https://github.com/griptape-ai/griptape-nodes-library-nuke/pull/163)
- Describe marks a parameter declared as `Sequence` or `list[Sequence]` with `is_sequence`, so a host
  can build a sequence input with a frame range.
  [#185](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/185)
- Describe reports a parameter whose declared type has no Nuke knob, such as a driver or a dict, as
  `GTUnknown` instead of `GTText`, so a host can show it as unsupported.
- The workflow list for hosts marks each workflow with `template` and `library_provided`, so a host
  can show templates apart from other workflows. A `templates_only` filter returns just templates,
  and internal workflows are no longer listed.

### Fixed

- A published gizmo on engine 0.105.0 handed Nuke the literal `{outputs}/...` macro for an artifact
  output instead of the file's path. The gizmo runner now resolves path macros itself when it
  hands outputs to Nuke, and Nuke End Flow stores outputs exactly as the engine hands them, so a
  published workflow no longer carries absolute paths from the author's machine.
  [#182](https://github.com/griptape-ai/griptape-nodes-library-nuke/pull/182)

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-nuke/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/griptape-ai/griptape-nodes-library-nuke/compare/v0.3.0...v0.4.0
