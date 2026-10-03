"""Pure cleaning functions applied to every raw CEAP row.

Every function here is deterministic and side-effect free so it can be unit
tested with plain values.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata

UFS: frozenset[str] = frozenset(
    "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
)

# Canonical short labels for the sub-quota (category) codes. The raw
# descriptions are upper-case, sometimes with trailing dots or odd commas.
CATEGORY_LABELS: dict[int, str] = {
    1: "Escritório de apoio",
    3: "Combustíveis e lubrificantes",
    4: "Consultorias e trabalhos técnicos",
    5: "Divulgação da atividade parlamentar",
    8: "Segurança",
    9: "Passagem aérea (reembolso)",
    10: "Telefonia",
    11: "Serviços postais",
    12: "Assinatura de publicações",
    13: "Alimentação do parlamentar",
    14: "Hospedagem",
    40: "Complementação do auxílio-moradia",
    119: "Locação de aeronaves",
    120: "Locação de veículos",
    121: "Locação de embarcações",
    122: "Táxi, pedágio e estacionamento",
    123: "Passagens terrestres, marítimas ou fluviais",
    137: "Cursos, palestras e eventos",
    145: "Tokens e certificados digitais",
    998: "Passagem aérea (SIGEPA)",
    999: "Passagem aérea (RPA)",
}

# Party acronyms whose official spelling is not all upper-case.
PARTY_CANONICAL: dict[str, str] = {
    "PCDOB": "PCdoB",
    "PC DO B": "PCdoB",
    "UNIAO": "UNIÃO",
    "MISSAO": "MISSÃO",
    "S.PART.": "S/PARTIDO",
    "S.PART": "S/PARTIDO",
    "SEM PARTIDO": "S/PARTIDO",
}

_WS = re.compile(r"\s+")
_NON_DIGIT = re.compile(r"\D")


def collapse_ws(text: str | None) -> str:
    return _WS.sub(" ", text or "").strip()


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


# --------------------------------------------------------------------------- #
# CNPJ / CPF
# --------------------------------------------------------------------------- #

def only_digits(text: str | None) -> str:
    return _NON_DIGIT.sub("", text or "")


def is_valid_cpf(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit() or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return False
    return True


def is_valid_cnpj(digits: str) -> bool:
    if len(digits) != 14 or not digits.isdigit() or digits == digits[0] * 14:
        return False
    weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    weights2 = [6] + weights1
    for size, weights in ((12, weights1), (13, weights2)):
        total = sum(int(d) * w for d, w in zip(digits[:size], weights))
        rest = total % 11
        check = 0 if rest < 2 else 11 - rest
        if check != int(digits[size]):
            return False
    return True


def normalize_document(raw: str | None) -> tuple[str | None, str | None]:
    """Return ``(digits, kind)`` where kind is ``"CNPJ"``, ``"CPF"`` or ``None``.

    The raw field is formatted inconsistently (``085.324.290/0013-1``,
    ``346.769.613/91  -``). Only digits matter. Values with lost leading zeros
    are zero-padded when the padded number has a valid check digit.
    Foreign suppliers and air tickets sometimes have no document at all.
    """
    digits = only_digits(raw)
    if not digits or len(digits.lstrip("0")) <= 2:
        # Empty, or a placeholder such as 00.000.000/0000-06 used for internal
        # Câmara services (RAMAL, CELULAR FUNCIONAL).
        return None, None
    if len(digits) == 14:
        return digits, "CNPJ"
    if len(digits) == 11:
        return digits, "CPF"
    if len(digits) < 11 and is_valid_cpf(digits.zfill(11)):
        return digits.zfill(11), "CPF"
    if len(digits) < 14 and is_valid_cnpj(digits.zfill(14)):
        return digits.zfill(14), "CNPJ"
    return digits, None


def format_document(digits: str | None, kind: str | None) -> str | None:
    """Human readable document. CPFs (private individuals) are masked."""
    if not digits:
        return None
    if kind == "CNPJ":
        d = digits
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if kind == "CPF":
        return mask_cpf(digits)
    return digits


def mask_cpf(digits: str) -> str:
    """Mask a CPF following the pattern used by Brazilian transparency portals."""
    d = only_digits(digits).zfill(11)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def supplier_key(digits: str | None, kind: str | None, name: str) -> str:
    """Stable identifier for a supplier.

    CNPJs are public and used as-is. CPFs are never exposed: the key keeps
    only the masked middle digits plus a short slug of the name.
    """
    if kind == "CNPJ" and digits:
        return digits
    if kind == "CPF" and digits:
        return f"pf-{digits[3:9]}-{slugify(name)[:24]}"
    return f"sd-{slugify(name)[:40]}"


def slugify(text: str) -> str:
    text = strip_accents(text or "").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "sem-nome"


# --------------------------------------------------------------------------- #
# Values and dates
# --------------------------------------------------------------------------- #

def parse_value(raw: str | None) -> float | None:
    """Parse a monetary value. Accepts ``1234.56`` and ``1.234,56``."""
    text = (raw or "").strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def parse_date(raw: str | None) -> dt.date | None:
    """Parse ``2025-02-07T00:00:00``, ``2025-02-07`` or ``07/02/2025``."""
    text = (raw or "").strip()
    if not text:
        return None
    for fmt, size in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10), ("%d/%m/%Y", 10)):
        try:
            return dt.datetime.strptime(text[:size], fmt).date()
        except ValueError:
            continue
    return None


def parse_int(raw: str | None) -> int | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Categories, parties, UF, names
# --------------------------------------------------------------------------- #

def normalize_category(code: str | int | None, description: str | None) -> tuple[int | None, str]:
    num = parse_int(str(code)) if code is not None else None
    if num in CATEGORY_LABELS:
        return num, CATEGORY_LABELS[num]
    text = collapse_ws(description).rstrip(". ").replace(" ,", ",")
    if not text:
        return num, "Outros"
    return num, text[:1].upper() + text[1:].lower()


def normalize_party(raw: str | None) -> str | None:
    text = collapse_ws(raw).upper()
    if not text:
        return None
    key = strip_accents(text)
    if key in PARTY_CANONICAL:
        return PARTY_CANONICAL[key]
    if text in PARTY_CANONICAL:
        return PARTY_CANONICAL[text]
    return text


def normalize_uf(raw: str | None) -> str | None:
    text = collapse_ws(raw).upper()
    return text if text in UFS else None


def normalize_name(raw: str | None) -> str:
    return collapse_ws(raw).strip(" .,;-")


def normalize_supplier_name(raw: str | None) -> str:
    name = normalize_name(raw).upper()
    return name or "SEM NOME INFORMADO"


def clean_url(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return text if text.startswith("http") else None


def clean_row(row: dict[str, str | None]) -> dict[str, object] | None:
    """Turn one raw CSV row into a typed, normalized record.

    Returns ``None`` for rows with no usable value or period.
    """
    value = parse_value(row.get("vlrLiquido"))
    year = parse_int(row.get("numAno"))
    month = parse_int(row.get("numMes"))
    if value is None or year is None or month is None or not 1 <= month <= 12:
        return None
    digits, kind = normalize_document(row.get("txtCNPJCPF"))
    supplier = normalize_supplier_name(row.get("txtFornecedor"))
    cat_code, cat_label = normalize_category(row.get("numSubCota"), row.get("txtDescricao"))
    deputy_id = parse_int(row.get("ideCadastro"))
    issued = parse_date(row.get("datEmissao"))
    return {
        "deputy_id": deputy_id,
        "deputy_name": normalize_name(row.get("txNomeParlamentar")),
        "legislature": parse_int(row.get("codLegislatura")),
        "uf": normalize_uf(row.get("sgUF")),
        "party": normalize_party(row.get("sgPartido")),
        "category_code": cat_code,
        "category": cat_label,
        "supplier_key": supplier_key(digits, kind, supplier),
        "supplier_name": supplier,
        "supplier_doc": format_document(digits, kind),
        "supplier_kind": kind,
        "doc_type": parse_int(row.get("indTipoDocumento")),
        "issued_on": issued,
        "value_document": parse_value(row.get("vlrDocumento")),
        "value_glosa": parse_value(row.get("vlrGlosa")),
        "value": value,
        "month": month,
        "year": year,
        "document_id": parse_int(row.get("ideDocumento")),
        "url": clean_url(row.get("urlDocumento")),
    }
