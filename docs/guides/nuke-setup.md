---
title: Setting up Nuke
description: Where the library finds Nuke, how to add an installation, the license, and the Nuke settings.
---

Read this page when the **Nuke Version** list is empty, when your Nuke is not listed, or when Nuke cannot find its license.

## What you need

- A Foundry Nuke installation on the same machine as Griptape Nodes. Annotator builds ship for Nuke 14, 15, 16 and 17.
- A Nuke license. If Nuke needs `foundry_LICENSE` to find it, add it as a secret under **Settings → API Keys & Secrets** (**Add Secret**). The library passes it to Nuke. A `foundry_LICENSE` value in `nuke.env` or in an installation's `env_overrides` is used instead.

Publishing a gizmo does not start Nuke, so it needs neither.

## Finding Nuke

The **Nuke Version** list on a Nuke Script node holds the installations from Engine Settings first, then the ones the library finds. It looks when you add the node and when you click **Refresh UI** on it, so click that after installing a new version. An installation the library finds uses the Nuke major version in the program's name to pick its Annotator build.

| System | Where it looks |
|--------|----------------|
| macOS | `/Applications/Nuke*` |
| Windows | `%ProgramFiles%\Nuke*` and `%ProgramFiles(x86)%\Nuke*` |
| Linux | `/usr/local/Nuke*`, `/opt/Nuke*` and `~/Nuke*` |

It also looks for a program named `Nuke` or `nuke` on your `PATH`. The Nuke crash reporter is left out.

## Adding Nuke from another location

Add entries to `nuke.installations` in Engine Settings:

```json
{
  "nuke": {
    "installations": [
      {
        "display_name": "Nuke 16.0v7",
        "executable_path": "/opt/nuke/16.0v7/Nuke16.0",
        "annotator_nuke_version": 16
      }
    ]
  }
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `display_name` | Yes | The name shown in **Nuke Version**. |
| `executable_path` | Yes | Full path to the Nuke program. |
| `annotator_nuke_version` | No | The Nuke major version. It picks which Annotator build **Open in Nuke** loads. A version with no Annotator build of its own uses the nearest lower one. Default 16. |
| `env_overrides` | No | Extra environment variables for Nuke runs with this installation. |
| `launch_mode` | No | `direct` starts Nuke itself and is the default. `rez` starts it through `rez-env`, with the packages listed in `launch_args`, or `nuke` if none. `custom` starts the command in `launch_args`, or `executable_path` if `launch_args` is empty. This applies to renders and baked copies. **Open in Nuke** always starts `executable_path` directly. |
| `launch_args` | No | The rez packages when `launch_mode` is `rez`. The command to start when `launch_mode` is `custom`. |
| `notes` | No | Your own notes. Not used. |

## Other Engine Settings

| Setting | Meaning |
|---------|---------|
| `nuke.executable` | The Nuke program to use when no installation is selected. |
| `nuke.env` | Environment variables for every Nuke run. An installation's `env_overrides` win over these. |
| `nuke.nuke_path` | Extra folders for `NUKE_PATH`. When this list is not empty, renders and baked copies use it in place of the `NUKE_PATH` from your environment. **Open in Nuke** puts them after the Annotator's own folder and before your environment's `NUKE_PATH`. |
| `nuke.annotator_nuke_version` | The Annotator build to load when no installation is selected. Default 16. |

## Choosing which Nuke runs

The **Nuke Executable (override)** field on the Nuke Script node holds a full path to a Nuke program. It is in the **Advanced** group, which starts collapsed.

- When a **Nuke Version** is selected, the render and **Save Baked Copy** use that installation's program and ignore this field.
- **Open in Nuke** starts the program in this field when it is set.
- When the **Nuke Version** list says "(none configured)", the render and the baked copy use this path, or the `nuke.executable` Engine Setting.
- The path must exist, or the run does not start, even when the render ignores it.
