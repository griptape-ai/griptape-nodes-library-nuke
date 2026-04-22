# Griptape Nodes: Foundry Nuke Library

A Griptape Nodes library for building workflows that run inside [Foundry Nuke](https://www.foundry.com/products/nuke-family). It provides flow-control nodes for authoring Nuke-targeted workflows and a publisher that packages a workflow as a versioned `.gizmo` you can drop into a Nuke script.

## Features

- **Nuke flow-control nodes** under the `Foundry Nuke` category:
  - `NukeStartFlow` – entry point for a Nuke-targeted workflow.
  - `NukeEndFlow` – terminal node; exposes `was_successful` and `result_details`.
- **Gizmo publisher** (`publish_gizmo/`): packages a workflow into a versioned `.gizmo` alongside a runner script and installs it into a Nuke plugin directory (default: `~/.nuke`).
- **Auto-discovery** of Nuke installations on macOS, Windows, and Linux, plus `NUKE_PATH` segment detection for picking an install target.
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

3. **Verify** that `Foundry Nuke` appears as a node category and that `Nuke Start Flow` / `Nuke End Flow` are available.

## Publishing a Workflow as a Nuke Gizmo

1. Build a workflow whose top-level flow starts with a `NukeStartFlow` node and ends with a `NukeEndFlow` node.
2. Trigger *Publish Workflow*. In the dialog, pick:
   - A **Nuke install** (auto-detected) to resolve plugin path candidates.
   - A **gizmo install path** – either `~/.nuke`, a path from `NUKE_PATH`, a Nuke-install plugins directory, or a custom path.
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

- [nuke_nodes/](nuke_nodes/) – `NukeStartFlow`, `NukeEndFlow`, and the advanced library entry point that registers the publish handler.
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
