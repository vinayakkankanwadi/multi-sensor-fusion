import sys
from pathlib import Path

# /app on the container; for host-side runs pytest is invoked from ui/
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
