from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from gastometro import load, outliers

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csv() -> Path:
    return FIXTURES / "ceap_amostra.csv"


@pytest.fixture
def broken_csv() -> Path:
    return FIXTURES / "ceap_sem_coluna.csv"


@pytest.fixture
def loaded_db(sample_csv: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    load.load_files(con, [sample_csv], legislature=57)
    load.load_quota(con, [2025])
    load.load_deputies(con, None)
    outliers.run_all(con)
    yield con
    con.close()
