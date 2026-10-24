"""pytest setup: make the project root importable so tests can `import api.index`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
