"""Filesystem locations for the application's data (database, backups, exports).

The database lives in a per-user writable directory so the app can run from a
read-only install location (portable folder or Program Files) without admin rights.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "SBCO-Recon"


def data_dir() -> Path:
    """Per-user application data directory, created on first use."""
    override = os.environ.get("SBCO_RECON_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        base = base / APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        base = base / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "sbco_recon.db"


def backups_dir() -> Path:
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def seed_dir() -> Path:
    """Directory holding the bundled seed CSVs (account codes, mismatch pairs).

    Works both from a source checkout (repo's data/seed) and a frozen build
    (PyInstaller places bundled files under sys._MEIPASS).
    """
    if getattr(sys, "_MEIPASS", None):  # PyInstaller one-file/one-folder build
        return Path(sys._MEIPASS) / "data" / "seed"
    return Path(__file__).resolve().parent.parent / "data" / "seed"
