import json

from gastometro import export, quota


def _flagged(con):
    return con.execute(
        "SELECT deputy_id, category_code, value FROM outlier_expenses ORDER BY value"
    ).fetchall()


def test_atypical_expense_is_flagged(loaded_db):
    assert (102, 3, 4800.0) in _flagged(loaded_db)


def test_moderately_high_expense_is_not_flagged(loaded_db):
    assert all(v != 320.0 for _, _, v in _flagged(loaded_db))


def test_small_groups_are_not_evaluated(loaded_db):
    # Office group in SP has only 5 rows: even R$ 20.000 is not evaluated.
    assert all(cat != 1 for _, cat, _ in _flagged(loaded_db))


def test_groups_without_variation_are_not_evaluated(loaded_db):
    # Phone bills in RJ are all R$ 100 -> MAD = 0 -> group skipped.
    assert all(cat != 10 for _, cat, _ in _flagged(loaded_db))


def test_only_one_flag_in_fixture(loaded_db):
    assert len(_flagged(loaded_db)) == 1


def test_robust_z_value(loaded_db):
    z, med = loaded_db.execute(
        "SELECT robust_z, median_value FROM outlier_expenses WHERE value = 4800").fetchone()
    assert z > 3.5
    assert 180 <= med <= 220


def test_leadership_rows_never_flagged(loaded_db):
    n = loaded_db.execute(
        "SELECT count(*) FROM outlier_expenses WHERE deputy_id IS NULL").fetchone()[0]
    assert n == 0


def test_month_share_uses_uf_quota(loaded_db):
    share, limit = loaded_db.execute("""
        SELECT share, monthly_limit FROM deputy_months
        WHERE deputy_id = 102 AND year = 2025 AND month = 6""").fetchone()
    assert limit == quota.monthly_limit("SP", 2025)
    assert share > 0.1


def test_quota_adjustment_2026():
    assert quota.monthly_limit("DF", 2025) == 36582.46
    assert quota.monthly_limit("DF", 2026) == round(36582.46 * 1.1375, 2)
    assert quota.monthly_limit(None, 2025) is None


def test_export_on_fixture(loaded_db, tmp_path):
    result = export.export_all(loaded_db, tmp_path, manifest={}, file_stats=[{
        "file": "Ano-2025.csv", "rows_read": 89, "rows_loaded": 87, "rows_rejected": 1,
        "rows_other_legislature": 1}])
    assert result["deputados"] == 3
    data = json.loads((tmp_path / "outliers.json").read_text(encoding="utf-8"))
    assert "não indica irregularidade" in data["aviso"]
    assert set(data["metodos"]) == {"despesas", "meses", "fornecedores"}
    assert data["despesas"][0]["valor"] == 4800.0
    assert data["despesas"][0]["url"].startswith("https://")
    dep = json.loads((tmp_path / "deputados" / "103.json").read_text(encoding="utf-8"))
    docs = [f["documento"] for f in dep["fornecedores"]]
    assert "***.982.247-**" in docs  # CPF supplier is masked
    assert not any("52998224725" in (d or "") for d in docs)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["liderancas"]["despesas"] == 1
