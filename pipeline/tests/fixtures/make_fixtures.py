"""Regenerate the small synthetic fixture CSVs used by the tests.

Run: python tests/fixtures/make_fixtures.py
The data is fictional (names, CNPJs and values are made up) but follows the
exact layout of the Câmara bulk files: UTF-8 with BOM, ``;`` separator,
every field quoted.
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).parent

COLUMNS = [
    "txNomeParlamentar", "cpf", "ideCadastro", "nuCarteiraParlamentar", "nuLegislatura",
    "sgUF", "sgPartido", "codLegislatura", "numSubCota", "txtDescricao",
    "numEspecificacaoSubCota", "txtDescricaoEspecificacao", "txtFornecedor", "txtCNPJCPF",
    "txtNumero", "indTipoDocumento", "datEmissao", "vlrDocumento", "vlrGlosa", "vlrLiquido",
    "numMes", "numAno", "numParcela", "txtPassageiro", "txtTrecho", "numLote",
    "numRessarcimento", "datPagamentoRestituicao", "vlrRestituicao", "nuDeputadoId",
    "ideDocumento", "urlDocumento",
]

DEPUTIES = {
    101: ("Deputada Exemplo A", "SP", "PT"),
    102: ("Deputado Exemplo B", "SP", "PL"),
    103: ("Deputado Exemplo C", "RJ", "PSD"),
}

CATS = {
    1: "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR",
    3: "COMBUSTÍVEIS E LUBRIFICANTES.",
    10: "TELEFONIA",
    998: "PASSAGEM AÉREA - SIGEPA",
}

_doc_id = 900000


def row(dep: int | None, cat: int, value: str, month: int, supplier: str, doc: str,
        year: int = 2025, legislature: str = "57", trecho: str = "", name: str | None = None,
        uf: str | None = None, party: str | None = None) -> dict[str, str]:
    global _doc_id
    _doc_id += 1
    nome, dep_uf, dep_party = DEPUTIES.get(dep, ("LIDERANÇA DO EXEMPLO", "NA", ""))
    return {
        "txNomeParlamentar": name or nome, "cpf": "", "ideCadastro": str(dep or ""),
        "nuCarteiraParlamentar": "", "nuLegislatura": "2023",
        "sgUF": uf or dep_uf, "sgPartido": party if party is not None else dep_party,
        "codLegislatura": legislature, "numSubCota": str(cat), "txtDescricao": CATS[cat],
        "numEspecificacaoSubCota": "0", "txtDescricaoEspecificacao": "",
        "txtFornecedor": supplier, "txtCNPJCPF": doc, "txtNumero": str(_doc_id),
        "indTipoDocumento": "0", "datEmissao": f"{year}-{month:02d}-10T00:00:00",
        "vlrDocumento": value, "vlrGlosa": "0", "vlrLiquido": value,
        "numMes": str(month), "numAno": str(year), "numParcela": "0", "txtPassageiro": "",
        "txtTrecho": trecho, "numLote": "1", "numRessarcimento": "",
        "datPagamentoRestituicao": "", "vlrRestituicao": "", "nuDeputadoId": str(dep or 1),
        "ideDocumento": str(_doc_id),
        "urlDocumento": f"https://www.camara.leg.br/cota-parlamentar/documentos/publ/1/{year}/{_doc_id}.pdf",
    }


def build_main() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    # 40 typical fuel receipts in SP between R$ 150 and R$ 250.
    for i in range(40):
        dep = 101 if i % 2 else 102
        value = f"{150 + (i * 37) % 101:.2f}"
        rows.append(row(dep, 3, value, 1 + i % 12, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81"))
    # One clearly atypical fuel receipt (R$ 4.800) -> must be flagged.
    rows.append(row(102, 3, "4800.00", 6, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81"))
    # A moderately high one (R$ 320) -> inside the expected range, NOT flagged.
    rows.append(row(101, 3, "320.00", 7, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81"))
    # Office expenses in SP: only 5 rows -> group too small, never evaluated.
    for i, v in enumerate(["1000", "1100", "900", "1050", "20000"]):
        rows.append(row(101, 1, v, i + 1, "IMOBILIÁRIA EXEMPLO", "085.324.290/0013-1"))
    # Phone bills in RJ, all identical -> MAD = 0, group not evaluated.
    for i in range(35):
        rows.append(row(103, 10, "100", 1 + i % 12, "TELEFONIA EXEMPLO S.A.", "33.000.118/0001-79"))
    rows.append(row(103, 10, "900", 12, "TELEFONIA EXEMPLO S.A.", "33.000.118/0001-79"))
    # Supplier that is a private individual (CPF, oddly formatted).
    rows.append(row(103, 1, "2500", 3, "Fulano  de   Tal ", "529.982.247/25  -"))
    # Air ticket refund (negative) with multi-line route field.
    rows.append(row(103, 998, "-1500.50", 4, "CIA AÉREA - EXEMPLO", "", trecho="BSB/GIG\nGIG/BSB"))
    # Party leadership (no ideCadastro).
    rows.append(row(None, 1, "1467", 2, "CAFÉ EXEMPLO LTDA", "11.222.333/0001-81"))
    # Previous legislature -> excluded from the 57th legislature load.
    rows.append(row(101, 3, "200", 1, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81",
                    year=2023, legislature="56"))
    # Unusable value -> rejected by validation.
    bad = row(101, 3, "abc", 5, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81")
    rows.append(bad)
    # Party written in a different case.
    rows.append(row(101, 3, "180", 8, "AUTO POSTO EXEMPLO LTDA", "11.222.333/0001-81", party="pt"))
    return rows


def write(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter=";", quoting=csv.QUOTE_ALL,
                                extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main_rows = build_main()
    write(HERE / "ceap_amostra.csv", main_rows, COLUMNS)
    broken = [c for c in COLUMNS if c != "vlrLiquido"]
    write(HERE / "ceap_sem_coluna.csv", main_rows[:3], broken)
    print(f"{len(main_rows)} linhas em ceap_amostra.csv")
