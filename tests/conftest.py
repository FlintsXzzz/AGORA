import os
import sys
from pathlib import Path

# Ensure project root modules (main.py, database.py, etc.) are importable with pytest's importlib mode
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Set dummy env vars for testing before any app modules are imported
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["NVIDIA_API_KEY"] = "dummy-key-for-testing"
