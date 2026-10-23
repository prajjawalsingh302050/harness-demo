"""Application settings, read once from the environment.

Every tunable lives here so the rest of the code never reads os.environ directly.
"""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "Harness Demo Shop"
    db_path: Path = ROOT / "data" / "shop.db"
    slow_query_ms: float = float(os.environ.get("SLOW_QUERY_MS", 5))
    orders_page_size: int = 50
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")
    # Vercel serves public/ from its CDN; locally FastAPI serves it.
    serve_static: bool = not os.environ.get("VERCEL")
    static_dir: Path = ROOT / "public"


settings = Settings()
