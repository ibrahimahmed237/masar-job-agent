"""Where a paused run is kept: LangGraph's SQLite checkpointer, in the same file as everything else."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from masar.adapters.sqlite_store import LOCK_WAIT_SECONDS


def open_checkpointer(path: Path | str) -> SqliteSaver:
    """A checkpointer on its own connection to the database file. Close its ``conn`` when done."""
    connection = sqlite3.connect(path, timeout=LOCK_WAIT_SECONDS, check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    return saver
