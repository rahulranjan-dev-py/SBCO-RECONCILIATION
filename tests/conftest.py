from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbco_recon.db.models import Base  # noqa: E402
from sbco_recon.db.seed import seed_if_empty  # noqa: E402


@pytest.fixture()
def session(tmp_path):
    """A fresh seeded database per test."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    with factory() as s:
        seed_if_empty(s)
        s.commit()
        yield s
