"""Write the API OpenAPI schema to packages/shared-types/openapi.json (LF endings)."""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
os.chdir(tempfile.mkdtemp())  # Settings reads ./.env; an empty cwd means no .env can load

from app.main import app  # noqa: E402

out = ROOT / "packages" / "shared-types" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2) + "\n", newline="\n")
