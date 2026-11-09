"""KubeFinOps research toolkit: trace-driven evaluation of right-sizing strategies.

The strategies are imported from the product (``backend/app/engines/rightsizing.py``)
so the paper evaluates exactly the code that runs in production.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_BACKEND = REPO / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
