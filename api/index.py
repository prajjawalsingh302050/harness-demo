"""Vercel entry point. Vercel's FastAPI preset serves the `app` defined here; locally run:
    uvicorn api.index:app --reload
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401
