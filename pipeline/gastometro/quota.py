"""Monthly CEAP limit per UF.

The quota varies by state because it is based on the price of air fares
between Brasília and each state capital.

Reference values: Ato da Mesa of 20 Jan 2023, in force from 1 Feb 2023
(range R$ 36.582,46 in DF to R$ 51.406,33 in RR). All 27 values match the
per-state table published by Itatiaia on 23 Oct 2025:
https://www.itatiaia.com.br/politica/saiba-quanto-cada-deputado-federal-pode-gastar-com-a-cota-parlamentar From 2026 the Mesa applied an inflation adjustment of
13.75% (Feb/2023 - Dec/2025); 2026 limits are estimated by applying that
factor. These numbers are used ONLY to normalise spending across states;
check the Câmara's current table before quoting them.
"""

from __future__ import annotations

QUOTA_2023: dict[str, float] = {
    "AC": 50426.26,
    "AL": 46737.90,
    "AM": 49363.92,
    "AP": 49168.58,
    "BA": 44804.65,
    "CE": 48245.57,
    "DF": 36582.46,
    "ES": 43217.71,
    "GO": 41300.86,
    "MA": 47945.49,
    "MG": 41886.51,
    "MS": 46336.64,
    "MT": 45221.83,
    "PA": 48021.25,
    "PB": 47826.36,
    "PE": 47470.60,
    "PI": 46765.57,
    "PR": 44665.66,
    "RJ": 41553.77,
    "RN": 48525.79,
    "RO": 49466.29,
    "RR": 51406.33,
    "RS": 46669.70,
    "SC": 45671.58,
    "SE": 45933.06,
    "SP": 42837.33,
    "TO": 45297.41,
}

ADJUSTMENT_2026 = 1.1375


def monthly_limit(uf: str | None, year: int) -> float | None:
    if uf not in QUOTA_2023:
        return None
    base = QUOTA_2023[uf]
    if year >= 2026:
        return round(base * ADJUSTMENT_2026, 2)
    return base


def rows(years: list[int]) -> list[tuple[str, int, float]]:
    """(uf, year, limit) tuples, handy for loading into DuckDB."""
    return [(uf, y, monthly_limit(uf, y)) for uf in sorted(QUOTA_2023) for y in years]
