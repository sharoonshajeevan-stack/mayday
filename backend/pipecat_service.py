# ============================================================================
# MAYDAY OS - REAL-TIME VOICE SERVICE (launcher script)
# File: backend/pipecat_service.py
#
# Convenience entry point so the real-time voice service can be started with:
#
#     cd backend
#     .venv\Scripts\python.exe pipecat_service.py
#
# (equivalent to: python -m pipecat_voice.service)
# ============================================================================

import os
import sys

# Make sure the backend directory is importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipecat_voice.service import main  # noqa: E402

if __name__ == "__main__":
    main()
