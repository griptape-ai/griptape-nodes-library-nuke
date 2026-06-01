from __future__ import annotations

import json
import logging
from pathlib import Path

from griptape_nodes.retained_mode.events.library_events import RegisterLibraryFromFileRequest
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

logger = logging.getLogger("griptape_nodes")


def register_bundled_libraries() -> None:
    """Register every library JSON listed in the companion's griptape_nodes_config.json.

    Paths in the config are stored relative to the companion bundle so the bundle stays
    portable; resolve them against this script's directory.
    """
    bundle_dir = Path(__file__).parent
    config_path = bundle_dir / "griptape_nodes_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    relative_paths = config["app_events"]["on_app_initialization_complete"]["libraries_to_register"]

    for rel in relative_paths:
        library_path = (bundle_dir / rel).resolve()
        logger.info("Registering library from %s", library_path)
        result = GriptapeNodes.handle_request(RegisterLibraryFromFileRequest(file_path=str(library_path)))
        if result.failed():
            msg = f"Failed to register library: {library_path}"
            raise ValueError(msg)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    register_bundled_libraries()
