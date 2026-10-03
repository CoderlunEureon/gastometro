import pytest

from gastometro import load, schema


def test_header_of_sample_is_valid(sample_csv):
    header, _ = load.iter_csv_rows(sample_csv)
    report = schema.validate_header(header)
    assert report.ok
    assert report.extra_columns == []
    assert header[0] == "txNomeParlamentar"  # BOM stripped


def test_missing_required_column_fails(broken_csv):
    header, _ = load.iter_csv_rows(broken_csv)
    report = schema.validate_header(header)
    assert report.missing_columns == ["vlrLiquido"]
    with pytest.raises(schema.SchemaError):
        load.read_file(broken_csv, legislature=57)


def test_unknown_column_is_only_a_warning():
    header = list(schema.REQUIRED_COLUMNS) + ["colunaNova"]
    report = schema.validate_header(header)
    assert report.ok and report.extra_columns == ["colunaNova"]


def test_validate_row_counts_problems():
    report = schema.ValidationReport()
    good = {"vlrLiquido": "10.5", "vlrDocumento": "10.5", "vlrGlosa": "0", "numMes": "2", "numAno": "2025"}
    assert schema.validate_row(good, report)
    assert not schema.validate_row({**good, "vlrLiquido": "abc"}, report)
    assert not schema.validate_row({**good, "numMes": "13"}, report)
    assert not schema.validate_row({**good, "numAno": ""}, report)
    assert report.rows == 4
    assert report.bad_values == {"vlrLiquido": 1, "numMes": 1, "numAno": 1}


def test_read_file_stats(sample_csv):
    records, stats = load.read_file(sample_csv, legislature=57)
    assert stats.rows_read == 89
    assert stats.rows_rejected == 1          # "abc" value
    assert stats.rows_other_legislature == 1  # legislature 56
    assert stats.rows_leadership == 1
    assert stats.rows_loaded == 87 == len(records)
    # multi-line quoted field survived parsing
    assert any(r["value"] == -1500.5 for r in records)
