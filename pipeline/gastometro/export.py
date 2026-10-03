"""Produce the compact JSON/Parquet aggregates consumed by the static site."""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import shutil
from pathlib import Path

import duckdb

from . import config, outliers, quota

log = logging.getLogger(__name__)

DEPUTY_FILTER = "deputy_id IS NOT NULL"
TOP_SUPPLIERS_SEARCH = 4000


def _r(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


def _write(path: Path, payload: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _round_dicts(rows: list[dict], *keys: str) -> list[dict]:
    for row in rows:
        for k in keys:
            if k in row:
                row[k] = _r(row[k])
    return rows


def export_meta(con, out: Path, manifest: dict, file_stats: list[dict]) -> dict:
    t = con.execute(f"""
        SELECT count(*), sum(value), count(DISTINCT deputy_id), count(DISTINCT supplier_key),
               min(year * 100 + month), max(year * 100 + month)
        FROM expenses WHERE {DEPUTY_FILTER}""").fetchone()
    lead = con.execute("SELECT count(*), sum(value) FROM expenses WHERE deputy_id IS NULL").fetchone()
    years = [r[0] for r in con.execute("SELECT DISTINCT year FROM expenses ORDER BY 1").fetchall()]
    files = []
    for s in file_stats:
        found = re.search(r"(\d{4})", s["file"])
        year = found.group(1) if found else ""
        m = manifest.get(year, {})
        files.append({
            "arquivo": s["file"], "ano": int(year) if year else None, "url": m.get("url"),
            "atualizado_na_fonte": m.get("last_modified"), "baixado_em": m.get("downloaded_at"),
            "linhas_lidas": s["rows_read"], "linhas_carregadas": s["rows_loaded"],
            "linhas_rejeitadas": s["rows_rejected"],
            "linhas_outra_legislatura": s["rows_other_legislature"],
        })
    meta = {
        "gerado_em": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "legislatura": config.LEGISLATURE,
        "anos": years,
        "periodo": {"inicio": f"{t[4] // 100}-{t[4] % 100:02d}", "fim": f"{t[5] // 100}-{t[5] % 100:02d}"},
        "totais": {"despesas": t[0], "valor": _r(t[1]), "deputados": t[2], "fornecedores": t[3]},
        "liderancas": {"despesas": lead[0], "valor": _r(lead[1])},
        "arquivos": files,
        "fonte": {
            "nome": "Câmara dos Deputados — Dados Abertos (Cota para o Exercício da Atividade Parlamentar)",
            "url": "https://www2.camara.leg.br/transparencia/cota-para-exercicio-da-atividade-parlamentar/dados-abertos-cota-parlamentar",
            "arquivos": config.BULK_URL.replace("{year}", "AAAA"),
            "api": config.API_URL,
        },
        "cota_por_uf": {uf: quota.monthly_limit(uf, max(years)) for uf in quota.QUOTA_2023},
    }
    _write(out / "meta.json", meta)
    return meta


def export_overview(con, out: Path) -> None:
    by_year = _round_dicts(_rows(con, f"""
        SELECT year AS ano, sum(value) AS total, count(*) AS despesas,
               count(DISTINCT deputy_id) AS deputados
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY year ORDER BY year"""), "total")
    monthly = _round_dicts(_rows(con, f"""
        SELECT year AS ano, month AS mes, sum(value) AS total
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY ALL ORDER BY year, month"""), "total")
    by_cat = _round_dicts(_rows(con, f"""
        SELECT year AS ano, category_code AS cod, any_value(category) AS categoria,
               sum(value) AS total, count(*) AS despesas
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY year, category_code ORDER BY year, total DESC"""),
        "total")
    by_party = _round_dicts(_rows(con, f"""
        WITH d AS (SELECT id, partido FROM deputies)
        SELECT e.year AS ano, d.partido, sum(e.value) AS total,
               count(DISTINCT e.deputy_id) AS deputados
        FROM expenses e JOIN d ON d.id = e.deputy_id
        GROUP BY ALL ORDER BY ano, total DESC"""), "total")
    by_uf = _round_dicts(_rows(con, f"""
        SELECT year AS ano, uf, sum(value) AS total, count(DISTINCT deputy_id) AS deputados
        FROM expenses WHERE {DEPUTY_FILTER} AND uf IS NOT NULL
        GROUP BY ALL ORDER BY ano, total DESC"""), "total")
    # Whole-period rows (ano = 0) so distinct deputy counts are exact.
    by_party += _round_dicts(_rows(con, """
        SELECT 0 AS ano, d.partido, sum(e.value) AS total, count(DISTINCT e.deputy_id) AS deputados
        FROM expenses e JOIN deputies d ON d.id = e.deputy_id
        GROUP BY ALL ORDER BY total DESC"""), "total")
    by_uf += _round_dicts(_rows(con, f"""
        SELECT 0 AS ano, uf, sum(value) AS total, count(DISTINCT deputy_id) AS deputados
        FROM expenses WHERE {DEPUTY_FILTER} AND uf IS NOT NULL
        GROUP BY ALL ORDER BY total DESC"""), "total")
    _write(out / "overview.json", {
        "por_ano": by_year, "mensal": monthly, "por_categoria": by_cat,
        "por_partido": by_party, "por_uf": by_uf,
        "nota": "Em por_partido e por_uf, ano = 0 significa o período inteiro.",
    })


def export_ranking(con, out: Path) -> None:
    deputies = con.execute("""
        SELECT id, nome, partido, uf, em_exercicio FROM deputies ORDER BY nome""").fetchall()
    idx = {d[0]: i for i, d in enumerate(deputies)}
    cats = con.execute(f"""
        SELECT category_code, any_value(category), sum(value) s FROM expenses
        WHERE {DEPUTY_FILTER} GROUP BY 1 ORDER BY s DESC""").fetchall()
    cidx = {c[0]: i for i, c in enumerate(cats)}
    rows = con.execute(f"""
        SELECT deputy_id, year, category_code, sum(value), count(*)
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY ALL ORDER BY 1, 2, 3""").fetchall()
    _write(out / "ranking.json", {
        "deputados": [list(d) for d in deputies],
        "categorias": [[c[0], c[1]] for c in cats],
        "colunas": ["deputado", "ano", "categoria", "total", "despesas"],
        "linhas": [[idx[r[0]], r[1], cidx[r[2]], _r(r[3]), r[4]] for r in rows],
    })


def export_deputies(con, out: Path) -> int:
    target = out / "deputados"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    deputies = _rows(con, "SELECT * FROM deputies ORDER BY id")
    totals = _rows(con, f"""
        SELECT deputy_id, sum(value) AS total FROM expenses WHERE {DEPUTY_FILTER} GROUP BY 1""")
    ranked = sorted(totals, key=lambda r: -r["total"])
    position = {r["deputy_id"]: i + 1 for i, r in enumerate(ranked)}

    def per(sql: str) -> dict[int, list[dict]]:
        grouped: dict[int, list[dict]] = {}
        for row in _rows(con, sql):
            grouped.setdefault(row.pop("deputy_id"), []).append(row)
        return grouped

    by_year = per(f"""
        SELECT e.deputy_id, e.year AS ano, sum(e.value) AS total, count(*) AS despesas,
               count(DISTINCT e.month) AS meses_com_gastos,
               any_value(q.monthly_limit) AS cota_mensal
        FROM expenses e LEFT JOIN quota_limits q ON q.uf = e.uf AND q.year = e.year
        WHERE e.{DEPUTY_FILTER} GROUP BY e.deputy_id, e.year ORDER BY e.year""")
    by_cat = per(f"""
        SELECT deputy_id, category_code AS cod, any_value(category) AS categoria,
               sum(value) AS total, count(*) AS despesas
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY ALL ORDER BY total DESC""")
    monthly = per(f"""
        SELECT deputy_id, year AS ano, month AS mes, sum(value) AS total
        FROM expenses WHERE {DEPUTY_FILTER} GROUP BY ALL ORDER BY ano, mes""")
    suppliers = per(f"""
        SELECT deputy_id, chave, nome, documento, total, despesas FROM (
            SELECT deputy_id, supplier_key AS chave, any_value(supplier_name) AS nome,
                   any_value(supplier_doc) AS documento, sum(value) AS total, count(*) AS despesas,
                   row_number() OVER (PARTITION BY deputy_id ORDER BY sum(value) DESC) AS rn
            FROM expenses WHERE {DEPUTY_FILTER} GROUP BY deputy_id, supplier_key)
        WHERE rn <= 15 ORDER BY total DESC""")
    largest = per(f"""
        SELECT deputy_id, data, ano, mes, categoria, fornecedor, documento, valor, url FROM (
            SELECT deputy_id, issued_on AS data, year AS ano, month AS mes, category AS categoria,
                   supplier_name AS fornecedor, supplier_doc AS documento, value AS valor, url,
                   row_number() OVER (PARTITION BY deputy_id ORDER BY value DESC) AS rn
            FROM expenses WHERE {DEPUTY_FILTER})
        WHERE rn <= 10 ORDER BY valor DESC""")
    flagged = per("""
        SELECT deputy_id, issued_on AS data, year AS ano, month AS mes, category AS categoria,
               supplier_name AS fornecedor, value AS valor, median_value AS mediana_grupo,
               times_median AS vezes_mediana, robust_z AS z, url
        FROM outlier_expenses ORDER BY times_median DESC""")
    uf_median = {(r["uf"], r["ano"]): r["mediana"] for r in _rows(con, f"""
        WITH t AS (SELECT deputy_id, uf, year, sum(value) s FROM expenses
                   WHERE {DEPUTY_FILTER} AND uf IS NOT NULL GROUP BY ALL)
        SELECT uf, year AS ano, median(s) AS mediana FROM t GROUP BY ALL""")}

    for d in deputies:
        did = d["id"]
        years = _round_dicts(by_year.get(did, []), "total", "cota_mensal")
        for y in years:
            y["mediana_uf"] = _r(uf_median.get((d["uf"], y["ano"])))
        payload = {
            "id": did, "nome": d["nome"], "partido": d["partido"],
            "partidos": d["partidos"] or [], "uf": d["uf"], "foto": d["foto"],
            "perfil": config.PROFILE_URL.format(id=did), "em_exercicio": d["em_exercicio"],
            "posicao": position.get(did), "de": len(ranked),
            "total": _r(next((t["total"] for t in totals if t["deputy_id"] == did), 0)),
            "por_ano": years,
            "por_categoria": _round_dicts(by_cat.get(did, []), "total"),
            "mensal": _round_dicts(monthly.get(did, []), "total"),
            "fornecedores": _round_dicts(suppliers.get(did, []), "total"),
            "maiores_despesas": _round_dicts(largest.get(did, []), "valor"),
            "pontos_fora_da_curva": [
                {**r, "valor": _r(r["valor"]), "mediana_grupo": _r(r["mediana_grupo"]),
                 "vezes_mediana": round(r["vezes_mediana"], 1), "z": round(r["z"], 1)}
                for r in flagged.get(did, [])[:30]
            ],
        }
        _write(target / f"{did}.json", payload)
    return len(deputies)


def export_suppliers(con, out: Path) -> None:
    deputies = con.execute("SELECT id, nome, partido, uf FROM deputies ORDER BY nome").fetchall()
    didx = {d[0]: i for i, d in enumerate(deputies)}
    cats = dict(con.execute(f"""SELECT category_code, any_value(category) FROM expenses
                                WHERE {DEPUTY_FILTER} GROUP BY 1""").fetchall())
    top = con.execute(f"""
        WITH s AS (
            SELECT r.*, row_number() OVER (ORDER BY total DESC) AS rn FROM supplier_reach r
        ), d AS (
            SELECT supplier_key, deputy_id, sum(value) AS v,
                   row_number() OVER (PARTITION BY supplier_key ORDER BY sum(value) DESC) AS rk
            FROM expenses WHERE {DEPUTY_FILTER} GROUP BY supplier_key, deputy_id
        )
        SELECT s.supplier_key, s.supplier_name, s.supplier_doc, s.total, s.documents, s.offices,
               s.main_category, list([d.deputy_id, round(d.v, 2)] ORDER BY d.v DESC)
        FROM s JOIN d ON d.supplier_key = s.supplier_key AND d.rk <= 5
        WHERE s.rn <= {TOP_SUPPLIERS_SEARCH}
        GROUP BY s.supplier_key, s.supplier_name, s.supplier_doc, s.total, s.documents,
                 s.offices, s.main_category
        ORDER BY s.total DESC""").fetchall()
    n_all = con.execute("SELECT count(*), sum(total) FROM supplier_reach").fetchone()
    _write(out / "fornecedores.json", {
        "total_fornecedores": n_all[0],
        "incluidos": len(top),
        "deputados": [list(d) for d in deputies],
        "categorias": {str(k): v for k, v in cats.items()},
        "colunas": ["chave", "nome", "documento", "total", "despesas", "gabinetes",
                    "categoria", "principais_deputados"],
        "linhas": [[r[0], r[1], r[2], _r(r[3]), r[4], r[5], r[6],
                    [[didx[int(x[0])], x[1]] for x in r[7]]] for r in top],
    })


def export_outliers(con, out: Path, limit: int = 400) -> dict:
    expenses = _rows(con, f"""
        SELECT o.deputy_id AS id, d.nome, d.partido, o.uf, o.issued_on AS data, o.year AS ano,
               o.month AS mes, o.category AS categoria, o.supplier_name AS fornecedor,
               o.supplier_doc AS documento, o.value AS valor, o.median_value AS mediana_grupo,
               o.upper_fence AS cerca_superior, o.times_median AS vezes_mediana,
               o.robust_z AS z, o.group_size AS tamanho_grupo, o.url
        FROM outlier_expenses o JOIN deputies d ON d.id = o.deputy_id
        ORDER BY o.times_median DESC, o.value DESC LIMIT {limit}""")
    for r in expenses:
        for k in ("valor", "mediana_grupo", "cerca_superior"):
            r[k] = _r(r[k])
        r["vezes_mediana"] = round(r["vezes_mediana"], 1)
        r["z"] = round(r["z"], 2)
    months = _rows(con, """
        SELECT m.deputy_id AS id, d.nome, d.partido, m.uf, m.year AS ano, m.month AS mes,
               m.total, m.monthly_limit AS cota_mensal, m.share AS proporcao,
               m.median_share AS mediana_proporcao, m.robust_z AS z
        FROM outlier_months m JOIN deputies d ON d.id = m.deputy_id
        ORDER BY m.robust_z DESC LIMIT 150""")
    for r in months:
        r["total"], r["cota_mensal"] = _r(r["total"]), _r(r["cota_mensal"])
        r["proporcao"], r["mediana_proporcao"] = round(r["proporcao"], 3), round(r["mediana_proporcao"], 3)
        r["z"] = round(r["z"], 2)
    cats = dict(con.execute("SELECT category_code, any_value(category) FROM expenses GROUP BY 1").fetchall())
    suppliers = _rows(con, """
        SELECT supplier_key AS chave, supplier_name AS nome, supplier_doc AS documento,
               main_category AS cod, offices AS gabinetes, parties AS partidos, ufs,
               documents AS despesas, total, p_cut AS corte_p99, median_offices AS mediana_gabinetes
        FROM outlier_suppliers ORDER BY offices DESC LIMIT 150""")
    for r in suppliers:
        r["categoria"] = cats.get(r["cod"])
        r["total"] = _r(r["total"])
        r["corte_p99"] = round(r["corte_p99"], 1)
    counts = {
        "despesas": con.execute("SELECT count(*) FROM outlier_expenses").fetchone()[0],
        "meses": con.execute("SELECT count(*) FROM outlier_months").fetchone()[0],
        "fornecedores": con.execute("SELECT count(*) FROM outlier_suppliers").fetchone()[0],
        "despesas_avaliadas": con.execute(f"""
            SELECT count(*) FROM expenses e JOIN outlier_groups g USING (category_code, uf)
            WHERE e.{DEPUTY_FILTER} AND e.value > 0 AND g.n >= {outliers.MIN_GROUP_SIZE}
              AND g.mad_log > 0""").fetchone()[0],
    }
    counts["despesas_por_categoria"] = _rows(con, """
        SELECT any_value(category) AS categoria, count(*) AS n
        FROM outlier_expenses GROUP BY category_code ORDER BY n DESC""")
    _write(out / "outliers.json", {
        "aviso": ("Os dados são oficiais. Um ponto fora da curva é apenas um valor "
                  "estatisticamente distante do típico para o grupo de comparação e não "
                  "indica irregularidade. Consulte sempre o documento original."),
        "metodos": outliers.METHODS,
        "parametros": {"z_modificado": outliers.MODIFIED_Z_THRESHOLD,
                       "iqr_k": outliers.IQR_MULTIPLIER, "grupo_minimo": outliers.MIN_GROUP_SIZE},
        "contagens": counts,
        "despesas": expenses, "meses": months, "fornecedores": suppliers,
    })
    return counts


def export_parquet(con, out: Path) -> None:
    """Monthly aggregate for analysts (deputy x month x category)."""
    path = (out / "gastos_mensais.parquet").as_posix()
    con.execute(f"""
        COPY (
            SELECT e.year AS ano, e.month AS mes, e.deputy_id AS deputado_id, d.nome AS deputado,
                   d.partido, e.uf, e.category_code AS cod_categoria, e.category AS categoria,
                   round(sum(e.value), 2) AS total, count(*) AS despesas
            FROM expenses e JOIN deputies d ON d.id = e.deputy_id
            GROUP BY ALL ORDER BY ano, mes, deputado_id, cod_categoria
        ) TO '{path}' (FORMAT parquet, COMPRESSION zstd)""")


def export_all(con, out: Path, manifest: dict, file_stats: list[dict]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    meta = export_meta(con, out, manifest, file_stats)
    export_overview(con, out)
    export_ranking(con, out)
    n = export_deputies(con, out)
    export_suppliers(con, out)
    counts = export_outliers(con, out)
    export_parquet(con, out)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    log.info("exportados %d deputados; %.2f MB em %s", n, size / 1e6, out)
    return {"meta": meta, "outliers": counts, "bytes": size, "deputados": n}
