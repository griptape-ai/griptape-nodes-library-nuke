# Changelog

All notable changes to the Nuke Nodes Library will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/2.0.0/), and each version is
the `library_version` in `griptape-nodes-library.json`.
**Breaking** marks a change that can stop a saved workflow from working without edits.

## [Unreleased]

<!-- Entries go in changelog.d/, one file each. See changelog.d/README.md. -->

## [0.5.0] - 2026-11-24

### Added

- The workflow list for hosts names the library that ships each library workflow in a new
  `library_name` field, so a host can group or label templates by library. It is empty for the
  user's own workflows.

### Changed

- **Breaking:** The library requires engine 0.111.0 or later. On an older engine from PyPI it no
  longer loads, so update the engine before updating the library.
- **Breaking:** Nuke acts only on the workflow it loaded. With none loaded, execute, the
  parameter-value verbs, execution state and cancel report that instead of driving the workflow
  open in the editor. A host that drove an editor's workflow without loading it must send
  `NukeLoadWorkflowRequest` for that workflow first.
- Loading a workflow from Nuke uses the copy an editor tab already has open, unsaved edits
  included, instead of reloading it from disk. Loading a workflow Nuke opened itself still reopens
  it from its file. A failed load leaves Nuke's previous workflow loaded, and the next load closes
  it only if Nuke opened it.

### Fixed

- The inputs and outputs Nuke reads, sets and runs with come from the workflow as it stands, so a
  Start Flow or End Flow parameter added in the editor works before the workflow is saved.
- The `Nuke Version` dropdown on the Nuke Script node lists only Nuke on Windows, instead of also
  listing Nuke's crash reporter, `nukeCrashFeedback`, for Nuke 14.1 and later.
  [#166](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/166)
- Nuke keeps working while the engine has other workflows open, such as editor tabs, instead of
  failing with `WorkflowNotNamedError`. Loading a workflow from Nuke replaces the one Nuke loaded
  before and leaves other open workflows alone.
  [#204](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/204)
- The Griptape node in Nuke now reports a run as failed when the workflow's End Flow never ran,
  naming the node the run stopped at. It used to report "Workflow completed successfully" with no
  outputs delivered.
  [#193](https://github.com/griptape-ai/griptape-nodes-library-nuke/issues/193)

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

[Unreleased]: https://github.com/griptape-ai/griptape-nodes-library-nuke/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/griptape-ai/griptape-nodes-library-nuke/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/griptape-ai/griptape-nodes-library-nuke/compare/v0.3.0...v0.4.0
