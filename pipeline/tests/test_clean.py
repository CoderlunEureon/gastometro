import datetime as dt

import pytest

from gastometro import clean


@pytest.mark.parametrize("raw, expected", [
    ("085.324.290/0013-1", ("08532429000131", "CNPJ")),
    ("11.222.333/0001-81", ("11222333000181", "CNPJ")),
    ("346.769.613/91  -", ("34676961391", "CPF")),
    ("", (None, None)),
    (None, (None, None)),
    ("123", ("123", None)),
    ("00.000.000/0000-06", (None, None)),  # placeholder for internal services
])
def test_normalize_document(raw, expected):
    assert clean.normalize_document(raw) == expected


def test_normalize_document_pads_lost_leading_zeros():
    # 07.575.651/0001-59 written without the leading zero
    assert clean.normalize_document("7575651000159") == ("07575651000159", "CNPJ")


def test_check_digits():
    assert clean.is_valid_cnpj("11222333000181")
    assert not clean.is_valid_cnpj("11222333000182")
    assert clean.is_valid_cpf("52998224725")
    assert not clean.is_valid_cpf("11111111111")


def test_format_document_masks_cpf():
    assert clean.format_document("11222333000181", "CNPJ") == "11.222.333/0001-81"
    masked = clean.format_document("52998224725", "CPF")
    assert masked == "***.982.247-**"
    assert "529" not in masked and "25" not in masked.split("-")[-1]


def test_supplier_key_never_contains_full_cpf():
    key = clean.supplier_key("52998224725", "CPF", "Fulano de Tal")
    assert "52998224725" not in key
    assert key.startswith("pf-")
    assert clean.supplier_key("11222333000181", "CNPJ", "X") == "11222333000181"


@pytest.mark.parametrize("raw, expected", [
    ("1467", 1467.0),
    ("281.3", 281.3),
    ("1.234,56", 1234.56),
    ("R$ 10,00", 10.0),
    ("-2113.91", -2113.91),
    ("", None),
    ("abc", None),
])
def test_parse_value(raw, expected):
    assert clean.parse_value(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2025-02-07T00:00:00", dt.date(2025, 2, 7)),
    ("2025-02-07", dt.date(2025, 2, 7)),
    ("07/02/2025", dt.date(2025, 2, 7)),
    ("", None),
    ("31/02/2025", None),
])
def test_parse_date(raw, expected):
    assert clean.parse_date(raw) == expected


def test_normalize_category():
    assert clean.normalize_category("3", "COMBUSTÍVEIS E LUBRIFICANTES.") == (3, "Combustíveis e lubrificantes")
    assert clean.normalize_category("998", "PASSAGEM AÉREA - SIGEPA") == (998, "Passagem aérea (SIGEPA)")
    code, label = clean.normalize_category("777", "NOVA CATEGORIA QUALQUER.")
    assert (code, label) == (777, "Nova categoria qualquer")


@pytest.mark.parametrize("raw, expected", [
    ("pt", "PT"),
    ("PCdoB", "PCdoB"),
    ("UNIÃO", "UNIÃO"),
    ("UNIAO", "UNIÃO"),
    ("S.PART.", "S/PARTIDO"),
    (" republicanos ", "REPUBLICANOS"),
    ("", None),
])
def test_normalize_party(raw, expected):
    assert clean.normalize_party(raw) == expected


def test_normalize_uf():
    assert clean.normalize_uf(" sp ") == "SP"
    assert clean.normalize_uf("NA") is None
    assert clean.normalize_uf("XX") is None


def test_names_and_urls():
    assert clean.normalize_supplier_name("  Fulano  de   Tal. ") == "FULANO DE TAL"
    assert clean.normalize_supplier_name("") == "SEM NOME INFORMADO"
    assert clean.clean_url("https://x/y.pdf") == "https://x/y.pdf"
    assert clean.clean_url("") is None


def test_clean_row_rejects_unusable_rows():
    assert clean.clean_row({"vlrLiquido": "abc", "numAno": "2025", "numMes": "1"}) is None
    assert clean.clean_row({"vlrLiquido": "10", "numAno": "2025", "numMes": "13"}) is None


def test_clean_row_full():
    rec = clean.clean_row({
        "txNomeParlamentar": "Fulana  Exemplo", "ideCadastro": "101", "codLegislatura": "57",
        "sgUF": "sp", "sgPartido": "pcdob", "numSubCota": "3",
        "txtDescricao": "COMBUSTÍVEIS E LUBRIFICANTES.", "txtFornecedor": "posto x",
        "txtCNPJCPF": "11.222.333/0001-81", "indTipoDocumento": "0",
        "datEmissao": "2025-03-01T00:00:00", "vlrDocumento": "100", "vlrGlosa": "0",
        "vlrLiquido": "100", "numMes": "3", "numAno": "2025", "ideDocumento": "5",
        "urlDocumento": "https://example/5.pdf",
    })
    assert rec["deputy_name"] == "Fulana Exemplo"
    assert rec["uf"] == "SP" and rec["party"] == "PCdoB"
    assert rec["supplier_doc"] == "11.222.333/0001-81"
    assert rec["issued_on"] == dt.date(2025, 3, 1)
    assert rec["value"] == 100.0 and rec["category_code"] == 3
