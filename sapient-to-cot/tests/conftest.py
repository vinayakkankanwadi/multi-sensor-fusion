import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE.parent))         # so `import sapient_to_cot` works
sys.path.insert(0, str(HERE))                # local imports
# proto bindings live in the regression image; for tests we need them on path:
sys.path.insert(0, str(HERE.parent / "regression"))
