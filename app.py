"""
Filofax AI Event Assistant — FastAPI entrypoint.

Run:
  python app.py

API: http://127.0.0.1:8002
"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    host = os.getenv("FILOFAX_HOST", "0.0.0.0")
    port = int(os.getenv("FILOFAX_PORT", "8002"))
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=os.getenv("FILOFAX_RELOAD", "false").lower() == "true",
    )
