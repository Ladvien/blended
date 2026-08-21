import sys
from pathlib import Path

# src-layout without requiring an editable install.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
