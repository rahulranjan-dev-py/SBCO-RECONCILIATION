"""Database backup/restore — a plain copy of the SQLite file, timestamped."""

from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from pathlib import Path

from ..paths import backups_dir, db_path


def create_backup(target_dir: Path | None = None) -> Path:
    """Snapshot the live database using SQLite's online backup API (WAL-safe)."""
    source = db_path()
    directory = target_dir or backups_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = directory / f"sbco_recon_backup_{stamp}.db"

    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def restore_backup(backup_file: Path) -> None:
    """Replace the live database with a backup. Caller must re-run init_db() after."""
    if not backup_file.exists():
        raise FileNotFoundError(backup_file)
    # Validate it is a SQLite database before overwriting anything.
    with sqlite3.connect(backup_file) as conn:
        conn.execute("PRAGMA schema_version").fetchone()
    live = db_path()
    # Keep a safety copy of the current database next to the backups.
    if live.exists():
        safety = backups_dir() / f"pre_restore_{dt.datetime.now():%Y%m%d_%H%M%S}.db"
        shutil.copy2(live, safety)
    for suffix in ("-wal", "-shm"):
        side = live.with_name(live.name + suffix)
        if side.exists():
            side.unlink()
    shutil.copy2(backup_file, live)
