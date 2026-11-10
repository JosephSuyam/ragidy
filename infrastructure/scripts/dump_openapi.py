"""Write the API OpenAPI schema to packages/shared-types/openapi.json (LF endings)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None  # no .env may load while dumping the schema

from app.main import app  # noqa: E402

out = ROOT / "packages" / "shared-types" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", newline="\n")
