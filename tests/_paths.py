"""Put the add-on and the Model Rail Generator on sys.path for the tests.

The Rail Generator is expected next to this repository (BLENDERWORKBENCHES/RAIL);
set MODEL_RAIL_PATH to the folder containing ``model_rail_generator`` to use another copy.
User presets go to temporary files so tests never touch your real presets.
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIL_ROOT = os.environ.get("MODEL_RAIL_PATH") or os.path.join(os.path.dirname(ROOT), "RAIL")

for p in (ROOT, RAIL_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

_tmp = tempfile.mkdtemp()
os.environ["SWITCH_FROG_PRESETS"] = os.path.join(_tmp, "frog_presets.json")
os.environ["MODEL_RAIL_PRESETS"] = os.path.join(_tmp, "rail_presets.json")


def publish_rail_api():
    """Import the Rail Generator's API and publish it as ``model_rail_api`` (what its register does)."""
    from model_rail_generator import api as rail
    sys.modules["model_rail_api"] = rail
    return rail
