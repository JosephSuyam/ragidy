import json
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).resolve().parents[3] / "packages" / "shared-types" / "openapi.json"


def test_openapi_snapshot_matches_app() -> None:
    app.openapi_schema = None  # a schema cached before a later change would hide the drift
    live = json.loads(json.dumps(app.openapi()))  # the dump script writes JSON, so compare that
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert live == committed, (
        "packages/shared-types/openapi.json is out of date with the API. "
        "Run `make types` and commit packages/shared-types/openapi.json "
        "and packages/shared-types/api.d.ts together."
    )
