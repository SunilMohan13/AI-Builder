"""Uvicorn entrypoint for the API container."""

import os

import uvicorn

from aeropulse_api.app import create_app

app = create_app()


def main() -> None:
    """Run the API on all interfaces.

    Local Compose publishes 8000. Render assigns ``PORT`` and routes the
    public URL there, so a fixed port would fail the health check.
    """
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("aeropulse_api.main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
