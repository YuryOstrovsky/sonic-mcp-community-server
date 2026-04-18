import os
import sys
from pathlib import Path

# Allow `python api/run.py` from the repo root by ensuring the repo root is on sys.path
# (otherwise only api/ — the script's dir — would be on sys.path, breaking `import api.app`).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("SONIC_MCP_PORT", "8000")),
        reload=False,
        log_level="info",
    )

