"""Version manifest manager for Nuke LiveGroup publishing.

Tracks publish history in a ``versions.json`` file inside the companion directory.
Provides:
- Hash-based detection of whether a full repackage is needed (vs. lightweight republish).
- Archiving of previous .nk files to a ``versions/`` subdirectory.
- Version number tracking for user-facing "Updated v1 -> v2" messaging.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class VersionEntry:
    version: int
    timestamp: str
    workflow_hash: str
    library_refs_hash: str


@dataclass
class VersionManifest:
    entries: list[VersionEntry] = field(default_factory=list)

    @property
    def latest(self) -> VersionEntry | None:
        return self.entries[-1] if self.entries else None

    @property
    def next_version(self) -> int:
        return (self.latest.version + 1) if self.latest else 1


class VersionManager:
    """Manages versions.json and version archiving for a single workflow's companion dir."""

    _MANIFEST_FILE = "versions.json"
    _VERSIONS_SUBDIR = "versions"

    def __init__(self, companion_dir: Path) -> None:
        self._companion_dir = companion_dir
        self._manifest_file = companion_dir / self._MANIFEST_FILE
        self._versions_dir = companion_dir / self._VERSIONS_SUBDIR

    def load_manifest(self) -> VersionManifest:
        """Load the manifest from disk, returning an empty manifest if not found."""
        if not self._manifest_file.exists():
            return VersionManifest()
        try:
            data = json.loads(self._manifest_file.read_text(encoding="utf-8"))
            entries = [VersionEntry(**e) for e in data.get("entries", [])]
            return VersionManifest(entries=entries)
        except Exception:
            return VersionManifest()

    def save_manifest(self, manifest: VersionManifest) -> None:
        """Persist the manifest to disk."""
        self._companion_dir.mkdir(parents=True, exist_ok=True)
        data = {"entries": [asdict(e) for e in manifest.entries]}
        self._manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def needs_full_repackage(self, library_refs: list) -> bool:
        """Return True if a full WorkflowPackager run is needed.

        A full repackage is needed when:
        - No previous publish exists (first time).
        - The library references have changed (new/updated libraries).
        - Critical package files are missing.
        """
        manifest = self.load_manifest()
        if manifest.latest is None:
            return True

        current_lib_hash = _hash_library_refs(library_refs)
        if manifest.latest.library_refs_hash != current_lib_hash:
            return True

        # Check for critical packaging files
        for required in ("pyproject.toml", "run_workflow.py", "run_button.py"):
            if not (self._companion_dir / required).exists():
                return True

        return False

    def archive_current_nk(self, nk_path: Path) -> None:
        """Copy the current .nk file to the versions/ subdirectory before overwriting.

        Does nothing if the .nk file does not exist yet (first publish).
        """
        if not nk_path.exists():
            return
        manifest = self.load_manifest()
        current_version = manifest.latest.version if manifest.latest else 1
        self._versions_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{nk_path.stem}_v{current_version}{nk_path.suffix}"
        shutil.copy2(nk_path, self._versions_dir / archive_name)

    def record_version(self, workflow_file: Path, library_refs: list) -> VersionEntry:
        """Add a new version entry to the manifest and return it."""
        manifest = self.load_manifest()
        entry = VersionEntry(
            version=manifest.next_version,
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            workflow_hash=_hash_file(workflow_file),
            library_refs_hash=_hash_library_refs(library_refs),
        )
        manifest.entries.append(entry)
        self.save_manifest(manifest)
        return entry

    def current_version(self) -> int | None:
        """Return the current version number, or None if never published."""
        manifest = self.load_manifest()
        return manifest.latest.version if manifest.latest else None


def _hash_file(path: Path) -> str:
    """Return a short SHA256 hex digest of a file's contents."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _hash_library_refs(library_refs: list) -> str:
    """Return a short SHA256 hex digest of the serialized library references list."""
    h = hashlib.sha256()
    h.update(json.dumps(sorted(str(r) for r in library_refs), sort_keys=True).encode())
    return h.hexdigest()[:16]
