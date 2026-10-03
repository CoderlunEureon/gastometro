"""Statistical outliers ("pontos fora da curva").

IMPORTANT: an outlier is only a value far from what is typical for a
comparison group. It does NOT indicate any irregularity. Every finding is
published with the method used and a link to the original receipt.

All methods run as SQL inside DuckDB on the ``expenses`` table so the same
code is exercised by the tests (on small fixtures) and by the real pipeline.
"""

from __future__ import annotations

import duckdb

# Iglewicz & Hoaglin (1993): |modified z| > 3.5 is the usual cut-off.
MODIFIED_Z_THRESHOLD = 3.5
# Tukey's "far out" fence.
IQR_MULTIPLIER = 3.0
MIN_GROUP_SIZE = 30
_Z_BR = f"{MODIFIED_Z_THRESHOLD:g}".replace(".", ",")

METHODS = {
    "despesas": (
        "Cada despesa é comparada com as despesas da mesma categoria feitas por "
        "deputados do mesmo estado (UF), o que já leva em conta que a cota tem "
        "valores diferentes por UF. Usamos estatística robusta, que não é "
        "distorcida pelos próprios valores extremos: calculamos a mediana e o MAD "
        "(desvio absoluto mediano) do logaritmo dos valores e o escore z modificado "
        "= 0,6745 × (x − mediana) / MAD. A despesa entra na lista só quando passa "
        f"de {_Z_BR} nesse escore e também fica acima da cerca de Tukey "
        f"(Q3 + {IQR_MULTIPLIER:g} × IQR) dos valores em reais. Grupos com menos de "
        f"{MIN_GROUP_SIZE} despesas ou sem variação (MAD = 0) não são avaliados. "
        "Estornos e valores negativos ficam de fora."
    ),
    "meses": (
        "Somamos as despesas de cada deputado em cada mês e dividimos pelo valor "
        "mensal da cota da UF dele, para comparar estados diferentes. O mês aparece "
        "quando essa proporção tem escore z modificado acima de "
        f"{_Z_BR} em relação a todos os meses do mesmo ano e passa de "
        "100% do valor mensal. Lembre que a regra da CEAP permite acumular o saldo "
        "não usado de meses anteriores dentro do mesmo ano, então meses acima do "
        "valor mensal são previstos pelas regras."
    ),
    "fornecedores": (
        "Para cada fornecedor contamos quantos gabinetes diferentes (deputados) "
        "fizeram pagamentos a ele. Dentro da categoria principal do fornecedor, "
        "listamos os que atenderam mais gabinetes do que 99% dos fornecedores da "
        "mesma categoria, com no mínimo 10 gabinetes. Passagens aéreas e "
        "complementação de auxílio-moradia ficam de fora porque são naturalmente "
        "concentradas em poucas empresas, assim como lançamentos sem CNPJ/CPF "
        "(serviços internos da Câmara, como ramais telefônicos). Estabelecimentos "
        "perto da Câmara, em Brasília (postos, papelarias, restaurantes), e grandes "
        "redes nacionais tendem a aparecer aqui simplesmente porque atendem muitos "
        "gabinetes ao mesmo tempo."
    ),
}

EXCLUDED_SUPPLIER_CATEGORIES = (9, 40, 998, 999)


def flag_expenses(con: duckdb.DuckDBPyConnection,
                  threshold: float = MODIFIED_Z_THRESHOLD,
                  iqr_k: float = IQR_MULTIPLIER,
                  min_group: int = MIN_GROUP_SIZE) -> None:
    """Create table ``outlier_expenses`` (one row per flagged expense)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE outlier_groups AS
        SELECT category_code, uf,
               count(*) AS n,
               median(ln(value)) AS med_log,
               mad(ln(value)) AS mad_log,
               median(value) AS median_value,
               quantile_cont(value, 0.25) AS q1,
               quantile_cont(value, 0.75) AS q3
        FROM expenses
        WHERE deputy_id IS NOT NULL AND uf IS NOT NULL AND value > 0
        GROUP BY category_code, uf
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE outlier_expenses AS
        SELECT e.*,
               g.n AS group_size,
               g.median_value,
               g.q3 + {iqr_k} * (g.q3 - g.q1) AS upper_fence,
               0.6745 * (ln(e.value) - g.med_log) / g.mad_log AS robust_z,
               e.value / g.median_value AS times_median
        FROM expenses e
        JOIN outlier_groups g USING (category_code, uf)
        WHERE e.deputy_id IS NOT NULL AND e.value > 0
          AND g.n >= {min_group} AND g.mad_log > 0
          AND 0.6745 * (ln(e.value) - g.med_log) / g.mad_log > {threshold}
          AND e.value > g.q3 + {iqr_k} * (g.q3 - g.q1)
    """)


def flag_months(con: duckdb.DuckDBPyConnection,
                threshold: float = MODIFIED_Z_THRESHOLD) -> None:
    """Create table ``outlier_months`` (deputy-months far above the typical share of the quota)."""
    con.execute("""
        CREATE OR REPLACE TABLE deputy_months AS
        SELECT e.deputy_id, e.year, e.month, any_value(e.uf) AS uf,
               sum(e.value) AS total, q.monthly_limit,
               sum(e.value) / q.monthly_limit AS share
        FROM expenses e
        JOIN quota_limits q ON q.uf = e.uf AND q.year = e.year
        WHERE e.deputy_id IS NOT NULL
        GROUP BY e.deputy_id, e.year, e.month, q.monthly_limit
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE outlier_months AS
        WITH s AS (
            SELECT year, median(share) AS med, mad(share) AS mad_share, count(*) AS n
            FROM deputy_months GROUP BY year
        )
        SELECT m.*, s.med AS median_share, s.n AS group_size,
               0.6745 * (m.share - s.med) / s.mad_share AS robust_z
        FROM deputy_months m JOIN s USING (year)
        WHERE s.mad_share > 0
          AND 0.6745 * (m.share - s.med) / s.mad_share > {threshold}
          AND m.share > 1
    """)


def flag_suppliers(con: duckdb.DuckDBPyConnection, quantile: float = 0.99,
                   min_offices: int = 10) -> None:
    """Create table ``outlier_suppliers`` (suppliers paid by unusually many offices)."""
    excluded = ", ".join(str(c) for c in EXCLUDED_SUPPLIER_CATEGORIES)
    con.execute(f"""
        CREATE OR REPLACE TABLE supplier_reach AS
        WITH per_cat AS (
            SELECT supplier_key, category_code, sum(value) AS cat_total
            FROM expenses
            WHERE deputy_id IS NOT NULL AND value > 0
            GROUP BY ALL
        ), main_cat AS (
            SELECT supplier_key, arg_max(category_code, cat_total) AS main_category
            FROM per_cat GROUP BY supplier_key
        )
        SELECT e.supplier_key,
               any_value(e.supplier_name) AS supplier_name,
               any_value(e.supplier_doc) AS supplier_doc,
               m.main_category,
               count(DISTINCT e.deputy_id) AS offices,
               count(DISTINCT e.party) AS parties,
               count(DISTINCT e.uf) AS ufs,
               count(*) AS documents,
               sum(e.value) AS total
        FROM expenses e JOIN main_cat m USING (supplier_key)
        WHERE e.deputy_id IS NOT NULL
        GROUP BY e.supplier_key, m.main_category
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE outlier_suppliers AS
        WITH s AS (
            SELECT main_category, quantile_cont(offices, {quantile}) AS p_cut,
                   median(offices) AS med, count(*) AS n
            FROM supplier_reach GROUP BY main_category
        )
        SELECT r.*, s.p_cut, s.med AS median_offices, s.n AS group_size
        FROM supplier_reach r JOIN s USING (main_category)
        WHERE r.main_category NOT IN ({excluded}) AND r.supplier_doc IS NOT NULL
          AND r.offices > s.p_cut AND r.offices >= {min_offices}
    """)


def run_all(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    flag_expenses(con)
    flag_months(con)
    flag_suppliers(con)
    return {
        "despesas": con.execute("SELECT count(*) FROM outlier_expenses").fetchone()[0],
        "meses": con.execute("SELECT count(*) FROM outlier_months").fetchone()[0],
        "fornecedores": con.execute("SELECT count(*) FROM outlier_suppliers").fetchone()[0],
    }
