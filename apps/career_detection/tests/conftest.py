"""DB guarantee for career-detection tests (root conftest provides the
project-wide socket guard — Prompt 2 ground rule 1)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_db(db):
    return db
