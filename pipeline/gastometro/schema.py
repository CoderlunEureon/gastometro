"""Schema of the CEAP bulk CSV and validation helpers.

The Câmara publishes one ``Ano-YYYY.csv`` per year: UTF-8 with BOM, ``;`` as
delimiter, every field quoted, decimal point ``.``. Column names are the
original camelCase Portuguese identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Columns the pipeline reads. If any of these disappears, the run must fail
# loudly instead of producing silently wrong aggregates.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "txNomeParlamentar",
    "ideCadastro",
    "codLegislatura",
    "sgUF",
    "sgPartido",
    "numSubCota",
    "txtDescricao",
    "txtFornecedor",
    "txtCNPJCPF",
    "indTipoDocumento",
    "datEmissao",
    "vlrDocumento",
    "vlrGlosa",
    "vlrLiquido",
    "numMes",
    "numAno",
    "ideDocumento",
    "urlDocumento",
)

# Columns that exist in the file but are not used (kept for documentation;
# an unknown extra column only produces a warning).
KNOWN_OPTIONAL_COLUMNS: tuple[str, ...] = (
    "cpf",
    "nuCarteiraParlamentar",
    "nuLegislatura",
    "numEspecificacaoSubCota",
    "txtDescricaoEspecificacao",
    "txtNumero",
    "numParcela",
    "txtPassageiro",
    "txtTrecho",
    "numLote",
    "numRessarcimento",
    "datPagamentoRestituicao",
    "vlrRestituicao",
    "nuDeputadoId",
)

NUMERIC_COLUMNS = ("vlrDocumento", "vlrGlosa", "vlrLiquido")
INTEGER_COLUMNS = ("numMes", "numAno", "numSubCota")


class SchemaError(ValueError):
    """Raised when a file does not match the expected layout."""


@dataclass
class ValidationReport:
    rows: int = 0
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    bad_values: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.missing_columns

    def add_bad(self, column: str) -> None:
        self.bad_values[column] = self.bad_values.get(column, 0) + 1


def normalize_header(header: list[str]) -> list[str]:
    """Strip the UTF-8 BOM, quotes and surrounding whitespace from header names."""
    return [h.replace("﻿", "").strip().strip('"').strip() for h in header]


def validate_header(header: list[str]) -> ValidationReport:
    cols = normalize_header(header)
    report = ValidationReport()
    report.missing_columns = [c for c in REQUIRED_COLUMNS if c not in cols]
    known = set(REQUIRED_COLUMNS) | set(KNOWN_OPTIONAL_COLUMNS)
    report.extra_columns = [c for c in cols if c not in known]
    return report


def require_header(header: list[str]) -> ValidationReport:
    report = validate_header(header)
    if not report.ok:
        raise SchemaError(
            "CSV sem colunas obrigatórias: " + ", ".join(report.missing_columns)
        )
    return report


def _is_number(text: str | None) -> bool:
    if text is None or text.strip() == "":
        return False
    try:
        float(text.replace(",", "."))
    except ValueError:
        return False
    return True


def validate_row(row: dict[str, str | None], report: ValidationReport) -> bool:
    """Type-check one raw row. Returns False when the row is unusable.

    A row is unusable when its net value or its year/month cannot be parsed;
    other problems are only counted in the report.
    """
    report.rows += 1
    usable = True
    for col in NUMERIC_COLUMNS:
        value = row.get(col)
        if value not in (None, "") and not _is_number(value):
            report.add_bad(col)
            if col == "vlrLiquido":
                usable = False
    if not _is_number(row.get("vlrLiquido")):
        usable = False
    for col in ("numMes", "numAno"):
        value = (row.get(col) or "").strip()
        if not value.isdigit():
            report.add_bad(col)
            usable = False
    mes = (row.get("numMes") or "").strip()
    if mes.isdigit() and not 1 <= int(mes) <= 12:
        report.add_bad("numMes")
        usable = False
    return usable
