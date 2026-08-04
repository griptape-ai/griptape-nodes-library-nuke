"""Griptape Annotator panel — runs inside Nuke's Python interpreter.

Stdlib + nuke + PySide2/PySide6 only. No Griptape dependency.
Nuke 15 ships PySide2/Python 3.10; Nuke 16+ ships PySide6/Python 3.11.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import traceback
from typing import Any

try:
    from PySide6 import QtCore, QtWidgets  # type: ignore[import-not-found]
    from PySide6.QtCore import Qt  # type: ignore[import-not-found]
except ImportError:
    from PySide2 import QtCore, QtWidgets  # type: ignore[import-not-found,no-redef]
    from PySide2.QtCore import Qt  # type: ignore[import-not-found,no-redef]

import nuke  # type: ignore[import-not-found]
import nukescripts  # type: ignore[import-not-found]

_SIDECAR_SCHEMA = "griptape-nuke-annotations/1.0"
_PANEL_ID = "griptape.annotator"
_PANEL_TITLE = "Griptape Annotator"

# Tile colors applied to annotated nodes in the Nuke node graph.
# Green for nodes with an I/O role; purple for expose-only nodes.
_TILE_COLOR_ROLE = 0x5FAD4EFF
_TILE_COLOR_EXPOSE = 0x9B59B6FF

# Artifact types available when marking a node as an input.
_INPUT_ARTIFACT_TYPES = ["ImageArtifact", "VideoUrlArtifact"]

# Artifact types available when marking a node as an output.
_OUTPUT_ARTIFACT_TYPES = ["ImageArtifact", "VideoUrlArtifact", "Sequence", "ThreeDUrlArtifact"]

# Knobs that are never useful to expose — purely internal Nuke state
_INTERNAL_KNOBS = frozenset(
    {
        "xpos",
        "ypos",
        "inputs",
        "selected",
        "tile_color",
        "gl_color",
        "note_font",
        "note_font_size",
        "note_font_color",
        "postage_stamp",
        "hide_input",
        "icon",
        "name",
        "help",
        "onCreate",
        "onDestroy",
        "knobChanged",
        "updateUI",
    }
)

# Knob classes that are structural/non-data — tabs, dividers, callbacks
_INTERNAL_KNOB_CLASSES = frozenset(
    {
        "Tab_Knob",
        "BeginTabGroup_Knob",
        "EndTabGroup_Knob",
        "Text_Knob",
        "PyScript_Knob",
        "Obsolete_Knob",
    }
)


def _script_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def _read_sidecar(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_sidecar(sidecar_path: str, script_path: str, data: dict[str, Any]) -> None:
    """Write the .gt.json sidecar atomically, preserving any existing knob_schema."""
    # Preserve knob_schema written by nuke -t introspect.py so we don't clobber it.
    if "knob_schema" not in data:
        existing = _read_sidecar(sidecar_path)
        if "knob_schema" in existing:
            data["knob_schema"] = existing["knob_schema"]

    data["schema"] = _SIDECAR_SCHEMA
    data["script"] = os.path.basename(script_path)
    data["script_hash"] = _script_hash(script_path)

    tmp_path = sidecar_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, sidecar_path)


class _KnobRow(QtWidgets.QWidget):
    """A single knob row with a checkbox, name label, and current-value label."""

    expose_changed = QtCore.Signal(str, bool)  # knob_name, exposed

    def __init__(self, node_name: str, knob_name: str, knob_label: str, value_str: str, exposed: bool) -> None:
        super().__init__()
        self._node_name = node_name
        self._knob_name = knob_name

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)

        self._checkbox = QtWidgets.QCheckBox()
        self._checkbox.setChecked(exposed)
        self._checkbox.setToolTip("Expose this knob to the Griptape node interface")
        self._checkbox.stateChanged.connect(self._on_state_changed)
        layout.addWidget(self._checkbox)

        name_label = QtWidgets.QLabel(knob_label or knob_name)
        name_label.setMinimumWidth(140)
        layout.addWidget(name_label)

        val_label = QtWidgets.QLabel(value_str)
        val_label.setStyleSheet("color: #888;")
        val_label.setMaximumWidth(120)
        val_label.setToolTip(value_str)
        layout.addWidget(val_label)
        layout.addStretch()

    def _on_state_changed(self, state: int) -> None:
        self.expose_changed.emit(self._knob_name, bool(state))


class _NodePanel(QtWidgets.QWidget):
    """Detail panel shown when a node card is selected."""

    expose_knob_toggled = QtCore.Signal(str, str, bool)  # node_name, knob_name, exposed

    def __init__(self, node_name: str, exposed_refs: set[str]) -> None:
        super().__init__()
        self._node_name = node_name
        self._exposed_refs = exposed_refs

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header = QtWidgets.QLabel(f"<b>{node_name}</b> — knobs")
        layout.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        self._knob_layout = QtWidgets.QVBoxLayout(content)
        self._knob_layout.setSpacing(0)
        scroll.setWidget(content)
        layout.addWidget(scroll)

        self._populate(node_name)

    def _populate(self, node_name: str) -> None:
        node = nuke.toNode(node_name)
        if node is None:
            return
        for knob_name, knob in node.knobs().items():
            if knob_name in _INTERNAL_KNOBS:
                continue
            if knob.Class() in _INTERNAL_KNOB_CLASSES:
                continue
            try:
                if not knob.visible():
                    continue
            except Exception:
                pass
            try:
                value_str = str(knob.value())
            except Exception:
                value_str = ""
            ref = f"{node_name}.{knob_name}"
            exposed = ref in self._exposed_refs
            row = _KnobRow(node_name, knob_name, knob.label() or knob_name, value_str, exposed)
            row.expose_changed.connect(lambda kn, exp, nn=node_name: self.expose_knob_toggled.emit(nn, kn, exp))
            self._knob_layout.addWidget(row)
        self._knob_layout.addStretch()


class GriptapeAnnotatorWidget(QtWidgets.QWidget):
    """Nuke dockable panel for annotating .nk scripts with Griptape I/O metadata."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._annotations: list[dict[str, Any]] = []
        self._exposed_refs: set[str] = set()
        self._node_panel: _NodePanel | None = None

        try:
            self._build_ui()
            self._load_current_script()
            global _panel_instance  # noqa: PLW0603
            _panel_instance = self
            print("[Griptape Annotator] panel initialised", file=sys.stderr)
        except Exception as exc:
            print(f"[Griptape Annotator] ERROR during init: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(6, 6, 6, 6)

        # Global toolbar — applies to both tabs
        toolbar = QtWidgets.QHBoxLayout()
        self._script_label = QtWidgets.QLabel("No script open")
        self._script_label.setWordWrap(True)
        toolbar.addWidget(self._script_label, stretch=1)
        refresh_btn = QtWidgets.QPushButton("Refresh")
        refresh_btn.setToolTip("Re-read the current Nuke script")
        refresh_btn.clicked.connect(self._load_current_script)
        toolbar.addWidget(refresh_btn)
        root_layout.addLayout(toolbar)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_annotate_tab(), "Annotate")
        root_layout.addWidget(tabs, stretch=1)

    def _build_annotate_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        splitter = QtWidgets.QSplitter(Qt.Horizontal)

        # Left: node list
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QtWidgets.QLabel("<b>Nodes</b>"))
        self._node_list = QtWidgets.QListWidget()
        self._node_list.currentItemChanged.connect(self._on_node_selected)
        left_layout.addWidget(self._node_list)

        # Role buttons below node list
        role_row = QtWidgets.QHBoxLayout()
        self._mark_input_btn = QtWidgets.QPushButton("Mark as Input")
        self._mark_input_btn.setToolTip("Mark selected Read node as a Griptape input port")
        self._mark_input_btn.clicked.connect(lambda: self._set_role("input"))
        self._mark_output_btn = QtWidgets.QPushButton("Mark as Output")
        self._mark_output_btn.setToolTip("Mark selected Write node as a Griptape output port")
        self._mark_output_btn.clicked.connect(lambda: self._set_role("output"))
        self._clear_role_btn = QtWidgets.QPushButton("Clear Role")
        self._clear_role_btn.clicked.connect(self._clear_role)
        role_row.addWidget(self._mark_input_btn)
        role_row.addWidget(self._mark_output_btn)
        role_row.addWidget(self._clear_role_btn)
        left_layout.addLayout(role_row)
        splitter.addWidget(left)

        # Right: knob panel placeholder
        self._right_placeholder = QtWidgets.QLabel("Select a node to browse its knobs.")
        self._right_placeholder.setAlignment(Qt.AlignCenter)
        splitter.addWidget(self._right_placeholder)
        splitter.setSizes([200, 300])

        self._splitter = splitter
        layout.addWidget(splitter, stretch=1)

        return widget

    def _build_overview_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 0)

        # Hash status row
        hash_row = QtWidgets.QHBoxLayout()
        hash_row.addWidget(QtWidgets.QLabel("Sidecar:"))
        self._hash_label = QtWidgets.QLabel("—")
        hash_row.addWidget(self._hash_label, stretch=1)
        layout.addLayout(hash_row)

        # Summary tree: Inputs / Outputs / Exposed Knobs sections
        self._overview_tree = QtWidgets.QTreeWidget()
        self._overview_tree.setHeaderLabels(["Node", "Name / Knob", "Type"])
        self._overview_tree.setColumnWidth(0, 140)
        self._overview_tree.setColumnWidth(1, 140)
        self._overview_tree.setRootIsDecorated(True)
        layout.addWidget(self._overview_tree, stretch=1)

        # Advanced collapsible section — raw JSON editor
        advanced_box = QtWidgets.QGroupBox("Advanced — Edit .gt.json directly")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        adv_layout = QtWidgets.QVBoxLayout(advanced_box)

        adv_content = QtWidgets.QWidget()
        adv_content_layout = QtWidgets.QVBoxLayout(adv_content)
        adv_content_layout.setContentsMargins(0, 0, 0, 0)

        self._json_editor = QtWidgets.QPlainTextEdit()
        self._json_editor.setPlaceholderText("No sidecar file exists yet.")
        self._json_editor.setStyleSheet("font-family: monospace;")
        self._json_editor.setMinimumHeight(120)
        adv_content_layout.addWidget(self._json_editor)

        save_raw_btn = QtWidgets.QPushButton("Save Raw JSON")
        save_raw_btn.setToolTip("Validate and write the JSON above to the .gt.json sidecar")
        save_raw_btn.clicked.connect(self._save_raw_json)
        adv_content_layout.addWidget(save_raw_btn)

        adv_layout.addWidget(adv_content)
        advanced_box.toggled.connect(adv_content.setVisible)
        adv_content.setVisible(False)

        layout.addWidget(advanced_box)

        return widget

    # ------------------------------------------------------------------
    # Script loading and overview refresh
    # ------------------------------------------------------------------

    def _load_current_script(self) -> None:
        try:
            self._load_current_script_impl()
        except Exception as exc:
            print(f"[Griptape Annotator] ERROR loading script: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    def _load_current_script_impl(self) -> None:
        script_path = nuke.scriptName()
        if script_path:
            self._script_label.setText(os.path.basename(script_path))
        else:
            self._script_label.setText("Unsaved script")

        self._node_list.clear()

        # Load existing sidecar if present
        if script_path:
            sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
            existing = _read_sidecar(sidecar_path)
            self._annotations = existing.get("annotations", [])
        else:
            self._annotations = []

        # Rebuild exposed_refs from the annotation list
        self._exposed_refs = set()
        for ann in self._annotations:
            for item in ann.get("gt_expose", []):
                if isinstance(item, dict):
                    ref = item.get("knob", "")
                else:
                    ref = str(item)
                if ref:
                    self._exposed_refs.add(ref)

        ann_by_node = {a["node"]: a for a in self._annotations}
        for node in nuke.allNodes():
            name = node.name()
            node_class = node.Class()
            ann = ann_by_node.get(name)
            role = ann.get("gt_role") if ann else None
            display = f"{name}  [{node_class}]"
            if role == "input":
                display = f"→ {display}"
            elif role == "output":
                display = f"← {display}"
            item = QtWidgets.QListWidgetItem(display)
            item.setData(Qt.UserRole, name)
            self._node_list.addItem(item)

        self._apply_tile_colors()
        self._refresh_overview()

        if self._node_panel is not None:
            node_name = self._node_panel._node_name
            old = self._splitter.widget(1)
            new_panel = _NodePanel(node_name, self._exposed_refs)
            new_panel.expose_knob_toggled.connect(self._on_expose_toggled)
            self._splitter.replaceWidget(1, new_panel)
            old.deleteLater()
            self._node_panel = new_panel

    def _refresh_overview(self) -> None:
        """Rebuild the Overview tab tree and JSON editor from the current sidecar."""
        self._overview_tree.clear()

        script_path = nuke.scriptName()
        if not script_path:
            self._hash_label.setText("(no script)")
            self._hash_label.setStyleSheet("color: #888;")
            self._json_editor.setPlainText("")
            return

        sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
        if not os.path.exists(sidecar_path):
            self._hash_label.setText("(no sidecar)")
            self._hash_label.setStyleSheet("color: #888;")
            self._json_editor.setPlainText("")
            return

        try:
            with open(sidecar_path, encoding="utf-8") as f:
                raw = f.read()
            data: dict[str, Any] = json.loads(raw)
        except Exception as exc:
            self._hash_label.setText(f"(read error: {exc})")
            self._hash_label.setStyleSheet("color: #E05050;")
            return

        # Hash status
        stored_hash = data.get("script_hash", "")
        try:
            current_hash = _script_hash(script_path)
            if stored_hash == current_hash:
                self._hash_label.setText("✓ current")
                self._hash_label.setStyleSheet("color: #5FAD4E;")
            else:
                self._hash_label.setText("⚠ stale — script changed since annotation")
                self._hash_label.setStyleSheet("color: #E8A000;")
        except OSError:
            self._hash_label.setText("(script file missing)")
            self._hash_label.setStyleSheet("color: #888;")

        # Summary tree
        inputs_item = QtWidgets.QTreeWidgetItem(self._overview_tree, ["Inputs", "", ""])
        outputs_item = QtWidgets.QTreeWidgetItem(self._overview_tree, ["Outputs", "", ""])
        knobs_item = QtWidgets.QTreeWidgetItem(self._overview_tree, ["Exposed Knobs", "", ""])

        for ann in data.get("annotations", []):
            node_name = ann.get("node", "")
            role = ann.get("gt_role")
            gt_name = ann.get("gt_name", "")
            gt_type = ann.get("gt_type", "")

            if role == "input":
                QtWidgets.QTreeWidgetItem(inputs_item, [node_name, gt_name, gt_type])
            elif role == "output":
                QtWidgets.QTreeWidgetItem(outputs_item, [node_name, gt_name, gt_type])

            for expose_item in ann.get("gt_expose", []):
                if isinstance(expose_item, dict):
                    knob_ref = expose_item.get("knob", "")
                    knob_type = expose_item.get("type", "")
                else:
                    knob_ref = str(expose_item)
                    knob_type = ""
                if "." in knob_ref:
                    node_part, knob_part = knob_ref.split(".", 1)
                else:
                    node_part, knob_part = node_name, knob_ref
                QtWidgets.QTreeWidgetItem(knobs_item, [node_part, knob_part, knob_type])

        inputs_item.setExpanded(True)
        outputs_item.setExpanded(True)
        knobs_item.setExpanded(True)

        # JSON editor — show prettified sidecar content (minus knob_schema to keep it readable)
        display_data = {k: v for k, v in data.items() if k != "knob_schema"}
        try:
            self._json_editor.setPlainText(json.dumps(display_data, indent=2))
        except Exception:
            self._json_editor.setPlainText(raw)

    # ------------------------------------------------------------------
    # Tile color — visual indicator in the Nuke node graph
    # ------------------------------------------------------------------

    def _apply_tile_colors(self) -> None:
        """Color annotated/exposed nodes in the node graph: green for I/O roles, purple for expose-only."""
        role_nodes: set[str] = set()
        expose_only_nodes: set[str] = set()

        for ann in self._annotations:
            node_name = ann.get("node", "")
            if not node_name:
                continue
            if ann.get("gt_role"):
                role_nodes.add(node_name)
            elif ann.get("gt_expose"):
                expose_only_nodes.add(node_name)

        # Nodes that appear in _exposed_refs but have no annotation entry yet
        for ref in self._exposed_refs:
            if "." in ref:
                node_name = ref.split(".", 1)[0]
                if node_name not in role_nodes:
                    expose_only_nodes.add(node_name)

        for node_name in role_nodes:
            node = nuke.toNode(node_name)
            if node:
                try:
                    node["tile_color"].setValue(_TILE_COLOR_ROLE)
                except Exception:
                    pass

        for node_name in expose_only_nodes:
            node = nuke.toNode(node_name)
            if node:
                try:
                    node["tile_color"].setValue(_TILE_COLOR_EXPOSE)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Annotate tab interactions
    # ------------------------------------------------------------------

    def _on_node_selected(self, current: Any, _previous: Any) -> None:
        if current is None:
            return
        node_name = current.data(Qt.UserRole)
        node_class = nuke.toNode(node_name).Class() if nuke.toNode(node_name) else ""

        # Input marking is only meaningful on Read nodes.
        # Output marking is available on any node — Write for 2D, WriteGeo/GeoExport for
        # geometry, Camera for camera matrix, etc.
        self._mark_input_btn.setEnabled(node_class == "Read")
        self._mark_output_btn.setEnabled(True)

        # Swap right panel
        old = self._splitter.widget(1)
        new_panel = _NodePanel(node_name, self._exposed_refs)
        new_panel.expose_knob_toggled.connect(self._on_expose_toggled)
        self._splitter.replaceWidget(1, new_panel)
        old.deleteLater()
        self._node_panel = new_panel

    def _set_role(self, role: str) -> None:
        item = self._node_list.currentItem()
        if item is None:
            return
        node_name = item.data(Qt.UserRole)
        gt_name = node_name.lower().replace(" ", "_")

        if role == "output":
            gt_type, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Output Artifact Type",
                f"Select the Griptape artifact type for {node_name!r}:",
                _OUTPUT_ARTIFACT_TYPES,
                0,
                False,
            )
            if not ok:
                return
        else:
            gt_type, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Input Artifact Type",
                f"Select the Griptape artifact type for {node_name!r}:",
                _INPUT_ARTIFACT_TYPES,
                0,
                False,
            )
            if not ok:
                return

        self._annotations = [a for a in self._annotations if a["node"] != node_name]
        self._annotations.append(
            {
                "node": node_name,
                "gt_role": role,
                "gt_name": gt_name,
                "gt_type": gt_type,
            }
        )
        self._save_sidecar()
        self._load_current_script()  # refresh list display

    def _clear_role(self) -> None:
        item = self._node_list.currentItem()
        if item is None:
            return
        node_name = item.data(Qt.UserRole)
        self._annotations = [a for a in self._annotations if a["node"] != node_name]
        # Reset tile color for this node
        node = nuke.toNode(node_name)
        if node:
            try:
                node["tile_color"].setValue(0)
            except Exception:
                pass
        self._save_sidecar()
        self._load_current_script()

    def _on_expose_toggled(self, node_name: str, knob_name: str, exposed: bool) -> None:
        ref = f"{node_name}.{knob_name}"
        if exposed:
            self._exposed_refs.add(ref)
        else:
            self._exposed_refs.discard(ref)
        self._save_sidecar()

    def _save_sidecar(self) -> None:
        script_path = nuke.scriptName()
        if not script_path:
            nuke.message("Save the Nuke script first before saving annotations.")
            return

        # Build exposed knob entries grouped by source node
        expose_by_node: dict[str, list[str]] = {}
        for ref in sorted(self._exposed_refs):
            if "." not in ref:
                continue
            node_name = ref.split(".", 1)[0]
            expose_by_node.setdefault(node_name, []).append(ref)

        # Merge expose lists into annotations, recording live knob class for type mapping.
        ann_by_node = {a["node"]: dict(a) for a in self._annotations}
        for node_name, refs in expose_by_node.items():
            if node_name not in ann_by_node:
                ann_by_node[node_name] = {"node": node_name}
            entries = []
            for ref in refs:
                entry: dict[str, str] = {"knob": ref}
                knob_name = ref.split(".", 1)[1] if "." in ref else ""
                node = nuke.toNode(node_name)
                if node and knob_name and knob_name in node.knobs():
                    entry["type"] = node[knob_name].Class()
                entries.append(entry)
            ann_by_node[node_name]["gt_expose"] = entries

        # Clear stale gt_expose for nodes whose last knob was un-exposed.
        for node_name, ann in ann_by_node.items():
            if node_name not in expose_by_node:
                ann.pop("gt_expose", None)

        # Drop ghost entries that carry neither a role nor any exposed knobs.
        annotations = [ann for ann in ann_by_node.values() if ann.get("gt_role") or ann.get("gt_expose")]
        data: dict[str, Any] = {"annotations": annotations}
        sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
        try:
            _write_sidecar(sidecar_path, script_path, data)
        except Exception as exc:
            print(f"[Griptape Annotator] ERROR saving sidecar: {exc}", file=sys.stderr)
            nuke.message(f"Failed to save annotations:\n{exc}")
            return

        self._apply_tile_colors()
        self._refresh_overview()

    def _save_raw_json(self) -> None:
        """Validate and write the JSON editor content directly to the .gt.json sidecar."""
        script_path = nuke.scriptName()
        if not script_path:
            nuke.message("Save the Nuke script first.")
            return

        raw = self._json_editor.toPlainText()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            nuke.message(f"Invalid JSON — not saved:\n{exc}")
            return

        sidecar_path = os.path.splitext(script_path)[0] + ".gt.json"
        try:
            tmp_path = sidecar_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, sidecar_path)
        except Exception as exc:
            nuke.message(f"Failed to save sidecar:\n{exc}")
            return

        self._load_current_script()
        nuke.message(f"Sidecar saved to:\n{sidecar_path}")


_panel_instance: GriptapeAnnotatorWidget | None = None


def _current_sidecar_path() -> str | None:
    path = nuke.root().name()
    if not path:
        return None
    return os.path.splitext(path)[0] + ".gt.json"


def _gt_mark_node(role: str) -> None:
    # thisNode() returns Root in Properties menu context; selectedNode() gives the right node.
    try:
        node = nuke.selectedNode()
    except Exception:
        node = None
    if node is None or node is nuke.root():
        nuke.message("Select a node in the Node Graph first, then right-click its Properties.")
        return
    sidecar_path = _current_sidecar_path()
    if not sidecar_path:
        nuke.message("Save the Nuke script first.")
        return
    script_path = nuke.root().name()

    if role == "output":
        choice = nuke.choice(
            "Select the Griptape artifact type:",
            "Output Type",
            _OUTPUT_ARTIFACT_TYPES,
        )
        if choice is None:
            return
        gt_type = _OUTPUT_ARTIFACT_TYPES[choice]
    else:
        choice = nuke.choice(
            "Select the Griptape artifact type:",
            "Input Type",
            _INPUT_ARTIFACT_TYPES,
        )
        if choice is None:
            return
        gt_type = _INPUT_ARTIFACT_TYPES[choice]

    data = _read_sidecar(sidecar_path)
    annotations = [a for a in data.get("annotations", []) if a.get("node") != node.name()]
    annotations.append(
        {
            "node": node.name(),
            "gt_role": role,
            "gt_name": node.name().lower(),
            "gt_type": gt_type,
        }
    )
    data["annotations"] = annotations
    _write_sidecar(sidecar_path, script_path, data)
    print(f"[Griptape Annotator] {node.name()} → {role} ({gt_type})", file=sys.stderr)


def _gt_clear_node_role() -> None:
    try:
        node = nuke.selectedNode()
    except Exception:
        node = None
    if node is None or node is nuke.root():
        return
    sidecar_path = _current_sidecar_path()
    if not sidecar_path:
        return
    script_path = nuke.root().name()
    data = _read_sidecar(sidecar_path)
    data["annotations"] = [a for a in data.get("annotations", []) if a.get("node") != node.name()]
    _write_sidecar(sidecar_path, script_path, data)
    print(f"[Griptape Annotator] cleared role for {node.name()}", file=sys.stderr)


def _gt_toggle_expose_knob(expose: bool) -> None:
    knob = nuke.thisKnob()
    node = nuke.thisNode()
    sidecar_path = _current_sidecar_path()
    if not sidecar_path:
        print("[Griptape Annotator] Expose Knob: script not saved yet", file=sys.stderr)
        nuke.message("Save the Nuke script first.")
        return
    if not knob or not node:
        print(f"[Griptape Annotator] Expose Knob: no knob/node context (knob={knob}, node={node})", file=sys.stderr)
        return
    try:
        script_path = nuke.root().name()
        knob_ref = f"{node.name()}.{knob.name()}"
        data = _read_sidecar(sidecar_path)
        ann_by_node = {a["node"]: dict(a) for a in data.get("annotations", [])}
        entry = ann_by_node.setdefault(node.name(), {"node": node.name()})
        existing_items: list[dict[str, str]] = [item for item in entry.get("gt_expose", []) if isinstance(item, dict)]
        existing_refs = [item["knob"] for item in existing_items]
        if expose and knob_ref not in existing_refs:
            new_item: dict[str, str] = {"knob": knob_ref, "type": knob.Class()}
            existing_items.append(new_item)
        elif not expose and knob_ref in existing_refs:
            existing_items = [item for item in existing_items if item["knob"] != knob_ref]
        entry["gt_expose"] = existing_items
        data["annotations"] = list(ann_by_node.values())
        _write_sidecar(sidecar_path, script_path, data)
        action = "exposed" if expose else "un-exposed"
        print(f"[Griptape Annotator] {knob_ref} {action}", file=sys.stderr)
        if _panel_instance is not None:
            _panel_instance._load_current_script()
    except Exception as exc:
        print(f"[Griptape Annotator] ERROR in _gt_toggle_expose_knob: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


def register() -> None:
    """Called from menu.py to register the panel with Nuke's UI."""
    try:
        nukescripts.registerWidgetAsPanel(
            "__import__('griptape_annotator_panel').GriptapeAnnotatorWidget",
            _PANEL_TITLE,
            _PANEL_ID,
        )
        print(f"[Griptape Annotator] registered panel '{_PANEL_ID}'", file=sys.stderr)
    except Exception as exc:
        print(f"[Griptape Annotator] ERROR: failed to register panel: {exc}", file=sys.stderr)
        return

    props = nuke.menu("Properties")
    props.addCommand("Griptape/Mark as Input", lambda: _gt_mark_node("input"))
    props.addCommand("Griptape/Mark as Output", lambda: _gt_mark_node("output"))
    props.addCommand("Griptape/Clear Griptape Role", _gt_clear_node_role)

    anim = nuke.menu("Animation")
    anim.addCommand("Griptape/Expose Knob", "__import__('griptape_annotator_panel')._gt_toggle_expose_knob(True)")
    anim.addCommand("Griptape/Un-expose Knob", "__import__('griptape_annotator_panel')._gt_toggle_expose_knob(False)")
