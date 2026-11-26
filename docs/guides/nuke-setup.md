---
title: Setting up Nuke
description: Where the library finds Nuke, how to add an installation, the license, and the Nuke settings.
---

The nodes in this library do not include Nuke. They run the copy of Foundry Nuke that is installed on your machine, so they need to know where it is and how to get a license for it. This page explains how the library finds Nuke, how to add an installation it does not find, and what to check when the **Nuke Version** list on the Nuke Script node is empty or Nuke cannot find its license.

Some settings here are environment variables. These are named values that the operating system passes to a program when it starts. Pipeline teams often use them to tell Nuke where its license and plugins are. If your studio set Nuke up for you, ask your pipeline team for the values.

## What you need

- A Foundry Nuke installation on the same machine as Griptape Nodes. The Annotator is a panel the library adds to Nuke (see [The Griptape Annotator panel](annotator-panel.md)). Annotator builds ship for Nuke 14, 15, 16 and 17.
- A Nuke license. If Nuke needs `foundry_LICENSE` to find it, add it as a secret under **Settings → API Keys & Secrets** (**Add Secret**). The library passes it to Nuke. A `foundry_LICENSE` value in `nuke.env` or in an installation's `env_overrides` is used instead.

Publishing a workflow as a gizmo does not start Nuke, so it needs neither. See [Publishing a workflow as a gizmo](publishing-a-gizmo.md).

## Finding Nuke

The **Nuke Version** list on a Nuke Script node holds the installations from Engine Settings first, then the ones the library finds. It looks when you add the node and when you click **Refresh UI** on it, so click that after installing a new version. An installation the library finds uses the Nuke major version in the program's name to pick its Annotator build.

| System | Where it looks |
|--------|----------------|
| macOS | `/Applications/Nuke*` |
| Windows | `%ProgramFiles%\Nuke*` and `%ProgramFiles(x86)%\Nuke*` |
| Linux | `/usr/local/Nuke*`, `/opt/Nuke*` and `~/Nuke*` |

It also looks for a program named `Nuke` or `nuke` on your `PATH`. The Nuke crash reporter is left out.

## Adding Nuke from another location

Engine Settings is the settings area of Griptape Nodes. Add entries to `nuke.installations` there. Each entry describes one Nuke installation:

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
| `env_overrides` | No | Extra environment variables, as name and value pairs, for Nuke runs with this installation. |
| `launch_mode` | No | `direct` starts Nuke itself and is the default. `rez` starts it through `rez-env` (the command of the rez package manager), with the packages listed in `launch_args`, or `nuke` if none. `custom` starts the command in `launch_args`, or `executable_path` if `launch_args` is empty. This applies to renders and baked copies. **Open in Nuke** always starts `executable_path` directly. |
| `launch_args` | No | The rez packages when `launch_mode` is `rez`. The command to start when `launch_mode` is `custom`. |
| `notes` | No | Your own notes. Not used. |

## Other Engine Settings

| Setting | Meaning |
|---------|---------|
| `nuke.executable` | The Nuke program to use when no installation is selected. |
| `nuke.env` | Environment variables for every Nuke run. An installation's `env_overrides` win over these. |
| `nuke.nuke_path` | Extra folders for `NUKE_PATH`, the list of folders where Nuke looks for plugins and gizmos. When this list is not empty, renders and baked copies use it in place of the `NUKE_PATH` from your environment. **Open in Nuke** puts them after the Annotator's own folder and before your environment's `NUKE_PATH`. |
| `nuke.annotator_nuke_version` | The Annotator build to load when no installation is selected. Default 16. |

## Choosing which Nuke runs

The **Nuke Executable (override)** field on the Nuke Script node holds a full path to a Nuke program. It is in the **Advanced** group, which starts collapsed.

- When a **Nuke Version** is selected, the render and **Save Baked Copy** use that installation's program and ignore this field.
- **Open in Nuke** starts the program in this field when it is set.
- When the **Nuke Version** list says "(none configured)", the render and the baked copy use this path, or the `nuke.executable` Engine Setting.
- The path must exist, or the run does not start, even when the render ignores it.
