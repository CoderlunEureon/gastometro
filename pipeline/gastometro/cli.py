"""Command line entry point: ``python -m gastometro run``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

import duckdb

from . import config, download, export, load, outliers


def parse_years(text: str | None) -> list[int]:
    if not text:
        return config.default_years()
    years: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            years.extend(range(int(a), int(b) + 1))
        else:
            years.append(int(part))
    return sorted(set(years))


def run(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    years = parse_years(args.years)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.sample:
        sample = Path(args.sample)
        paths = [sample] if sample.is_file() else sorted(sample.glob("*.csv"))
        api_file = None
        manifest = {}
    else:
        paths = []
        if not args.skip_download:
            for y in years:
                paths.append(download.download_year(y, raw_dir))
            api_file = download.download_deputies(raw_dir)
        else:
            paths = [raw_dir / f"Ano-{y}.csv.zip" for y in years if (raw_dir / f"Ano-{y}.csv.zip").exists()]
            api_file = raw_dir / f"deputados-{config.LEGISLATURE}.json"
        manifest = download.load_manifest(raw_dir)
    if not paths:
        logging.error("nenhum arquivo de entrada encontrado")
        return 1

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    stats = load.load_files(con, paths, legislature=config.LEGISLATURE)
    load.load_quota(con, years)
    load.load_deputies(con, api_file)
    counts = outliers.run_all(con)
    result = export.export_all(con, Path(args.out), manifest, [asdict(s) for s in stats])
    con.close()

    summary = {
        "arquivos": [asdict(s) for s in stats],
        "linhas_lidas": sum(s.rows_read for s in stats),
        "linhas_carregadas": sum(s.rows_loaded for s in stats),
        "pontos_fora_da_curva": counts,
        "deputados": result["deputados"],
        "saida_bytes": result["bytes"],
        "segundos": round(time.perf_counter() - t0, 1),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gastometro", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="baixa, valida, limpa, carrega e exporta")
    p.add_argument("--years", help="ex.: 2023-2026 ou 2024,2025 (padrão: 2023 até o ano atual)")
    p.add_argument("--raw-dir", default=str(config.RAW_DIR))
    p.add_argument("--db", default=str(config.DB_PATH))
    p.add_argument("--out", default=str(config.OUT_DIR))
    p.add_argument("--skip-download", action="store_true", help="usa apenas arquivos já baixados")
    p.add_argument("--sample", help="CSV (ou pasta de CSVs) de amostra, modo offline")
    p.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
