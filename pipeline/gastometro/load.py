"""Read raw files, validate, clean and load into DuckDB."""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import duckdb
import pyarrow as pa

from . import clean, quota, schema

log = logging.getLogger(__name__)

csv.field_size_limit(10_000_000)

EXPENSE_SCHEMA = pa.schema([
    ("deputy_id", pa.int64()),
    ("deputy_name", pa.string()),
    ("legislature", pa.int32()),
    ("uf", pa.string()),
    ("party", pa.string()),
    ("category_code", pa.int32()),
    ("category", pa.string()),
    ("supplier_key", pa.string()),
    ("supplier_name", pa.string()),
    ("supplier_doc", pa.string()),
    ("supplier_kind", pa.string()),
    ("doc_type", pa.int32()),
    ("issued_on", pa.date32()),
    ("value_document", pa.float64()),
    ("value_glosa", pa.float64()),
    ("value", pa.float64()),
    ("month", pa.int32()),
    ("year", pa.int32()),
    ("document_id", pa.int64()),
    ("url", pa.string()),
    ("source_file", pa.string()),
])


@dataclass
class FileStats:
    file: str
    rows_read: int = 0
    rows_loaded: int = 0
    rows_rejected: int = 0
    rows_other_legislature: int = 0
    rows_leadership: int = 0
    extra_columns: list[str] = field(default_factory=list)
    bad_values: dict[str, int] = field(default_factory=dict)


def iter_csv_rows(path: Path) -> tuple[list[str], Iterator[dict[str, str]]]:
    """Open a ``.csv`` or ``.csv.zip`` and return (header, row iterator)."""
    if path.suffix == ".zip":
        zf = zipfile.ZipFile(path)
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        stream = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    else:
        stream = path.open(encoding="utf-8-sig", newline="")
    reader = csv.reader(stream, delimiter=";", quotechar='"')
    header = schema.normalize_header(next(reader))

    def rows() -> Iterator[dict[str, str]]:
        try:
            for values in reader:
                if not values or values == [""]:
                    continue
                yield dict(zip(header, values))
        finally:
            stream.close()

    return header, rows()


def read_file(path: Path, legislature: int | None) -> tuple[list[dict], FileStats]:
    header, rows = iter_csv_rows(path)
    report = schema.require_header(header)
    stats = FileStats(file=path.name, extra_columns=report.extra_columns)
    if report.extra_columns:
        log.warning("%s: colunas novas não utilizadas: %s", path.name, report.extra_columns)
    records: list[dict] = []
    for raw in rows:
        stats.rows_read += 1
        if not schema.validate_row(raw, report):
            stats.rows_rejected += 1
            continue
        rec = clean.clean_row(raw)
        if rec is None:
            stats.rows_rejected += 1
            continue
        if legislature is not None and rec["legislature"] not in (None, legislature):
            stats.rows_other_legislature += 1
            continue
        if rec["deputy_id"] is None:
            # Party leaderships (Liderança do X / LID.GOV) also use the quota but
            # are not individual deputies; they are counted but kept apart.
            stats.rows_leadership += 1
        rec["source_file"] = path.name
        records.append(rec)
    stats.rows_loaded = len(records)
    stats.bad_values = dict(report.bad_values)
    return records, stats


def to_arrow(records: Iterable[dict]) -> pa.Table:
    records = list(records)
    columns = {name: [r.get(name) for r in records] for name in EXPENSE_SCHEMA.names}
    return pa.table(columns, schema=EXPENSE_SCHEMA)


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP TABLE IF EXISTS expenses")
    con.register("__empty", to_arrow([]))
    con.execute("CREATE TABLE expenses AS SELECT * FROM __empty")
    con.unregister("__empty")


def load_files(con: duckdb.DuckDBPyConnection, paths: list[Path],
               legislature: int | None) -> list[FileStats]:
    create_schema(con)
    all_stats: list[FileStats] = []
    for path in paths:
        records, stats = read_file(path, legislature)
        table = to_arrow(records)
        con.register("__batch", table)
        con.execute("INSERT INTO expenses SELECT * FROM __batch")
        con.unregister("__batch")
        log.info("%s: %d lidas, %d carregadas, %d rejeitadas", path.name,
                 stats.rows_read, stats.rows_loaded, stats.rows_rejected)
        all_stats.append(stats)
    con.execute("DROP TABLE IF EXISTS ingest_stats")
    con.execute("CREATE TABLE ingest_stats (payload JSON)")
    con.executemany("INSERT INTO ingest_stats VALUES (?)",
                    [[json.dumps(asdict(s), ensure_ascii=False)] for s in all_stats])
    return all_stats


def load_quota(con: duckdb.DuckDBPyConnection, years: list[int]) -> None:
    con.execute("DROP TABLE IF EXISTS quota_limits")
    con.execute("CREATE TABLE quota_limits (uf VARCHAR, year INTEGER, monthly_limit DOUBLE)")
    con.executemany("INSERT INTO quota_limits VALUES (?, ?, ?)", quota.rows(years))


def load_deputies(con: duckdb.DuckDBPyConnection, api_file: Path | None) -> None:
    """Deputies dimension: CSV is the source of truth, API adds photo/status."""
    con.execute("DROP TABLE IF EXISTS api_deputies")
    con.execute("""CREATE TABLE api_deputies (id BIGINT, nome VARCHAR, partido VARCHAR,
                   uf VARCHAR, foto VARCHAR, em_exercicio BOOLEAN)""")
    if api_file and api_file.exists():
        payload = json.loads(api_file.read_text(encoding="utf-8"))
        current = set(payload.get("em_exercicio", []))
        seen: dict[int, tuple] = {}
        for d in payload.get("deputados", []):
            # The API repeats a deputy when party/UF changed; keep the last one.
            seen[d["id"]] = (d["id"], clean.normalize_name(d.get("nome")),
                             clean.normalize_party(d.get("siglaPartido")),
                             clean.normalize_uf(d.get("siglaUf")), d.get("urlFoto"),
                             d["id"] in current)
        con.executemany("INSERT INTO api_deputies VALUES (?, ?, ?, ?, ?, ?)", list(seen.values()))

    con.execute("""
        CREATE OR REPLACE TABLE deputies AS
        WITH latest AS (
            SELECT deputy_id,
                   arg_max(deputy_name, year * 100 + month) AS nome,
                   arg_max(party, year * 100 + month) AS partido_csv,
                   arg_max(uf, year * 100 + month) AS uf_csv,
                   list(DISTINCT party ORDER BY party) FILTER (WHERE party IS NOT NULL) AS partidos
            FROM expenses WHERE deputy_id IS NOT NULL GROUP BY deputy_id
        )
        SELECT l.deputy_id AS id,
               coalesce(l.nome, a.nome) AS nome,
               l.partido_csv AS partido,
               coalesce(l.uf_csv, a.uf) AS uf,
               l.partidos,
               coalesce(a.foto, 'https://www.camara.leg.br/internet/deputado/bandep/' || l.deputy_id || '.jpg') AS foto,
               coalesce(a.em_exercicio, false) AS em_exercicio
        FROM latest l LEFT JOIN api_deputies a ON a.id = l.deputy_id
    """)
