# Griptape Nodes: Foundry Nuke Library

A Griptape Nodes library for building workflows that run inside [Foundry Nuke](https://www.foundry.com/products/nuke-family). It provides flow-control nodes for authoring Nuke-targeted workflows, a publisher that packages a workflow as a versioned `.gizmo` you can drop into a Nuke script, and a `NukeScriptNode` that runs an existing `.nk` script headlessly and surfaces its annotated nodes as typed ports on the Griptape canvas.

## Features

- **Nuke flow-control nodes** under the `Foundry Nuke` category:
  - `NukeStartFlow` – entry point for a Nuke-targeted workflow.
  - `NukeEndFlow` – terminal node; exposes `was_successful` and `result_details`.
- **NukeScriptNode** – runs a `.nk` script headlessly via `nuke -t`, surfaces annotated Read/Write nodes as typed input/output ports on the canvas, and supports per-knob value overrides. Inputs accept images, video, and raw file paths; outputs can be images, image sequences, video, or 3D geometry.
- **Griptape Annotator** – a dockable panel that runs inside the Nuke GUI for tagging I/O nodes and promoting knobs to the Griptape interface.
- **Gizmo publisher** (`publish_gizmo/`): packages a workflow into a versioned `.gizmo` alongside a runner script and installs it into a Nuke plugin directory (default: `~/.nuke`).
- **`NUKE_PATH` detection**: extra plugin directories from `NUKE_PATH` are surfaced as gizmo install targets in the publish dialog, alongside the default `~/.nuke`.
- **Griptape menu integration**: publishing writes a `menu.py` that adds a `Griptape` submenu to Nuke's Nodes toolbar and a `Refresh Griptape Gizmos` command on the main menu bar. Multiple published versions of the same workflow are grouped under a per-workflow submenu.
- **Nuke-aware output paths**: the bundled `project.yml` is rewritten so workflow outputs land next to the `.nk` file (under `griptape_outputs/<workflow_name>/...`).

## Configuration

Copy [.env.example](.env.example) to `.env` and set `NUKE_PATH` if you want extra plugin directories surfaced as install targets in the publish dialog. `~/.nuke` is always listed and is the default.

## Install the Library

1. **Clone the repository** into your Griptape Nodes workspace:

   ```bash
   cd "$(gtn config show workspace_directory)"
   git clone https://github.com/griptape-ai/griptape-nodes-library-nuke.git
   ```

2. **Register the library** in the Griptape Nodes editor:

   - Open *Settings > Libraries*.
   - Click *+ Add Library* and enter the path to [griptape-nodes-library.json](griptape-nodes-library.json) inside the cloned directory.
   - Close the settings panel and click *Refresh Libraries*.

3. **Verify** that `Foundry Nuke` appears as a node category and that `Nuke Start Flow` / `Nuke End Flow` / `Nuke Script Node` are available.

## NukeScriptNode

`NukeScriptNode` lets you drive an existing Nuke script from Griptape. Point it at a `.nk` file, annotate which nodes are inputs and outputs using the Griptape Annotator panel, and the node grows typed ports matching those annotations. At run time it invokes Nuke headlessly (`nuke -t`) and returns rendered output files as typed Griptape artifacts.

### Quick start

1. Drop a **Nuke Script Node** onto the canvas.
2. Set **Script Path** to your `.nk` file.
3. Click **Open in Nuke** — this launches Nuke with the Griptape Annotator panel loaded and any current knob overrides pre-applied.
4. In Nuke, open **Panels > Griptape Annotator**. On the **Annotate** tab, mark Read nodes as inputs and Write nodes as outputs, optionally expose knobs from other nodes, then click **Save Annotations**.
5. Back in Griptape, click **Refresh UI** (or re-select the script path). The node grows typed input/output ports matching your annotations.
6. Wire inputs, set **Frame Start** / **Frame End**, and run the node.

### Annotation sidecar

Annotations are stored in a `<script>.gt.json` file next to the `.nk`. The Annotator panel writes this file automatically. If the `.nk` is saved after annotation the node warns that the sidecar may be stale — re-open in Nuke and re-save annotations to refresh it.

### Exposed knobs

Knobs promoted via the Annotator panel's **Expose** tab appear as Griptape parameters grouped under their node name. Leave a field empty to use the value already in the script; set it to override before the render.

### Inputs

Read nodes annotated as inputs accept `str` (file path), `ImageArtifact`, `ImageUrlArtifact`, `VideoUrlArtifact`, or `BlobArtifact` values. URL-based artifacts are downloaded to a temporary file before the render.

### Outputs

Write nodes annotated as outputs surface in the **Outputs** group after the node runs. The artifact type depends on the annotation:

| Annotation type        | Griptape output                                           |
|------------------------|-----------------------------------------------------------|
| `ImageArtifact` / `ImageUrlArtifact` | `ImageUrlArtifact` (single rendered frame)  |
| `VideoUrlArtifact`     | `VideoUrlArtifact` (rendered video file, e.g. `.mp4`)     |
| `ImageSequenceArtifact`| `ListArtifact` of `ImageUrlArtifact` — one per rendered frame |
| `ThreeDUrlArtifact` / `GLTFUrlArtifact` | `ThreeDUrlArtifact` (`.obj` or `.glb`)   |

### Advanced parameters

| Parameter                  | Description                                                                                                                         |
|----------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| Nuke Executable (override) | Absolute path to a Nuke binary; overrides the Engine Settings selection for this node only.                                         |
| Baked Script Output Path   | Destination for a baked copy of the `.nk`.                                                                                          |
| Save Baked Copy            | Writes a copy of the script with all current parameter values baked into the knobs — useful for archiving or manual inspection.     |

## Configuring Nuke Installations

### Auto-discovery

The library scans standard install locations on startup and populates the **Nuke Version** dropdown automatically:

| OS      | Locations scanned                                      |
|---------|--------------------------------------------------------|
| macOS   | `/Applications/Nuke*`                                  |
| Windows | `%ProgramFiles%\Nuke*`, `%ProgramFiles(x86)%\Nuke*`   |
| Linux   | `/usr/local/Nuke*`, `/opt/Nuke*`, `~/Nuke*`            |

It also checks `PATH` for executables named `Nuke` or `nuke`. Click **Refresh UI** on the node to re-run discovery after installing a new version.

### Manual configuration via Engine Settings

For installs in non-standard locations, add entries to the `nuke.installations` key in Engine Settings:

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

| Field                    | Required | Description                                                                        |
|--------------------------|----------|------------------------------------------------------------------------------------|
| `display_name`           | yes      | Label shown in the **Nuke Version** dropdown                                       |
| `executable_path`        | yes      | Absolute path to the Nuke binary                                                   |
| `annotator_nuke_version` | no       | Nuke major version; controls which Annotator panel build is loaded (default: `16`) |
| `env_overrides`          | no       | Extra environment variables merged into the Nuke subprocess                        |
| `notes`                  | no       | Free-text notes; not used at runtime                                               |

### Additional engine settings

| Key               | Description                                                            |
|-------------------|------------------------------------------------------------------------|
| `nuke.executable` | Fallback Nuke binary path used when no installation entry is selected  |
| `nuke.env`        | Global environment variables injected into every Nuke subprocess       |
| `nuke.nuke_path`  | List of extra directories appended to `NUKE_PATH` for every invocation |

### Foundry license

Set `foundry_LICENSE` in the Griptape Secrets panel. It is injected into the Nuke subprocess automatically — do not hardcode it in `env_overrides`.

## Publishing a Workflow as a Nuke Gizmo

1. Build a workflow whose top-level flow starts with a `NukeStartFlow` node and ends with a `NukeEndFlow` node.
2. Trigger *Publish Workflow*. In the dialog, pick:
   - A **gizmo install path** – either `~/.nuke`, a path from `NUKE_PATH`, or a custom path.
   - An **update mode** to pick between creating a new version and overwriting the current one.
3. The publisher writes, under the chosen install directory:

   ```
   <install_dir>/
     init.py                     # appends pluginAddPath for the griptape dir
     griptape/
       menu.py                   # Griptape menu + refresh command
       <workflow>_v<N>.gizmo     # versioned gizmo
       <workflow>/
         v<N>/<workflow>.py      # workflow file for version N
         run_workflow.py         # runner executed inside Nuke
         run_button.py           # gizmo "Run" knob handler
         project.yml             # Nuke-specific output conventions
         ...                     # libraries, config, .env, pyproject.toml
   ```

4. Inside Nuke, use the `Griptape` menu on the Nodes toolbar to create the gizmo, or run `Griptape > Refresh Griptape Gizmos` from the main menu bar after publishing to pick up new versions without restarting Nuke.

## Repository Layout

- [nuke_nodes/](nuke_nodes/) – `NukeStartFlow`, `NukeEndFlow`, `NukeScriptNode`, and the advanced library entry point that registers the publish handler.
- [execution/](execution/) – subprocess launch layer: `DirectSubprocessProvider`, `NukeInstallation`, installation discovery.
- [script_parser/](script_parser/) – pure-Python `.nk` parser and `.gt.json` sidecar reader/writer (no Nuke dependency).
- [nuke_runner/](nuke_runner/) – headless runner scripts executed inside `nuke -t` (stdlib only).
- [nuke_plugin/](nuke_plugin/) – Griptape Annotator panel (PySide2/PySide6, runs inside the Nuke GUI).
- [publish_gizmo/](publish_gizmo/) – gizmo publisher, builder, validator, writer, Nuke install discovery, publish options, workflow runner, and gizmo run-button script.
- [workflows/templates/](workflows/templates/) – workflow templates shipped with the library.
- [griptape-nodes-library.json](griptape-nodes-library.json) – library manifest (nodes, category, metadata, bundled workflows).
- [Makefile](Makefile) – version bumping, dependency sync, lint/format/type checks.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, checks, and the release process. Quick reference:

```bash
make install        # install all dependencies via uv
make check          # format, lint, types, JSON validation
make fix            # auto-fix formatting and lint issues
```

## Additional Resources

- [Griptape Nodes](https://github.com/griptape-ai/griptape-nodes)
- [Griptape Framework](https://github.com/griptape-ai/griptape)
- [Griptape Nodes Directory](https://github.com/griptape-ai/griptape-nodes-directory)
- [Griptape Discord](https://discord.gg/griptape)
- [Foundry Nuke plugin/gizmo path docs](https://learn.foundry.com/nuke/content/comp_environment/configuring_nuke/loading_gizmos_plugins_scripts.html)

## License

Apache License 2.0. See [LICENSE](LICENSE).
