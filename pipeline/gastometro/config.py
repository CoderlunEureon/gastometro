"""Paths, URLs and constants shared by the pipeline."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = PIPELINE_DIR.parent
RAW_DIR = REPO_DIR / "data" / "raw"
DB_PATH = REPO_DIR / "data" / "gastometro.duckdb"
OUT_DIR = REPO_DIR / "site" / "public" / "data"

# Bulk CSV files published by the Câmara dos Deputados (one zip per year).
BULK_URL = "https://www.camara.leg.br/cotas/Ano-{year}.csv.zip"
# Open data API (used only to enrich deputies with photo/current party).
API_URL = "https://dadosabertos.camara.leg.br/api/v2"
PHOTO_URL = "https://www.camara.leg.br/internet/deputado/bandep/{id}.jpg"
PROFILE_URL = "https://www.camara.leg.br/deputados/{id}"

# 57th legislature (Feb 2023 - Jan 2027).
LEGISLATURE = 57
FIRST_YEAR = 2023


def default_years(today: _dt.date | None = None) -> list[int]:
    today = today or _dt.date.today()
    return list(range(FIRST_YEAR, today.year + 1))
