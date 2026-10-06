"""Export FastAPI OpenAPI 3 document to docs/openapi/openapi.v1.json."""

from __future__ import annotations

import json
from pathlib import Path

from aeropulse_api.app import create_app


def main() -> None:
    """Write the OpenAPI spec next to other docs."""
    app = create_app()
    spec = app.openapi()
    target = Path("docs/openapi/openapi.v1.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
