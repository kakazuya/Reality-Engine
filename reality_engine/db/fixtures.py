"""
Test Fixture & Isolation Utilities Module
Provides helpers for creating isolated temporary databases, seeding test fixtures,
and running test suites hermetically without side-effects on workspace artifacts.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator, Optional, Tuple
from contextlib import contextmanager

from reality_engine.config import FIXTURES_DIR, DATA_DIR
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.pipeline.bootstrap import BootstrapManager


def create_isolated_test_db(
    temp_dir: Optional[Path | str] = None,
    bootstrap_full: bool = True,
    days: int = 25,
    top: int = 200,
) -> Tuple[DatabaseManager, Repository, Path]:
    """
    Creates an isolated temporary SQLite database and optionally bootstraps it
    with deterministic test fixtures.
    """
    if temp_dir is None:
        target_dir = Path(tempfile.mkdtemp(prefix="reality_engine_fixture_"))
    else:
        target_dir = Path(temp_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

    db_path = target_dir / "test_equity_intelligence.db"
    db = DatabaseManager(db_path=db_path)
    repo = Repository(manager=db)

    if bootstrap_full:
        mgr = BootstrapManager(
            db_path=db_path,
            db_manager_inst=db,
            repository_inst=repo,
        )
        mgr.bootstrap(days=days, top=top, verify=False)

    return db, repo, target_dir


@contextmanager
def isolated_test_context(bootstrap_full: bool = True) -> Generator[Tuple[DatabaseManager, Repository, Path], None, None]:
    """
    Context manager providing an isolated temporary database environment
    that automatically cleans up on exit.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="reality_engine_ctx_"))
    try:
        db, repo, target_dir = create_isolated_test_db(
            temp_dir=temp_dir,
            bootstrap_full=bootstrap_full,
        )
        yield db, repo, target_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
