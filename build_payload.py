"""
BLOCK 5a — Tính toàn bộ số liệu bằng pandas, xuất ra JSON.
"""
import json
import pandas as pd
from pathlib import Path

WAREHOUSE = Path("warehouse")
DATA = Path("data")
PERIOD = "2026-09"

fact_pnl = pd.read_parquet(WAREHOUSE / "fact_pnl.parquet")
cur = fact_pnl[fact_pnl.period == PERIOD]
pl = cur.groupby(["pnl_group", "scenario"]).amount.sum().unstack("scenario").fillna(0)

revenue_a, revenue_b = pl.loc["Revenue", "Actual"], pl.loc["Revenue", "Budget"]
cogs_a, cogs_b = pl.loc["COGS", "Actual"], pl.loc["COGS", "Budget"]
opex_lines = ["Store Opex", "G&A", "UNMAPPED", "D&A"]
ebit_a = revenue_a - cogs_a - pl.loc[opex_lines, "Actual"].sum()
ebit_b = revenue_b - cogs_b - pl.loc[opex_lines, "Budget"].sum()
gm_a = 100 * (revenue_a - cogs_a) / revenue_a
gm_b = 100 * (revenue_b - cogs_b) / revenue_b

rev_cur = cur[cur.pnl_group == "Revenue"]
by_store = rev_cur.groupby(["cost_center", "scenario"]).amount.sum().unstack("scenario").fillna(0)
by_store["var"] = by_store.get("Actual", 0) - by_store.get("Budget", 0)
by_store_m = (by_store["var"] / 1e6).round(0).sort_values()

va = pd.read_csv(DATA / "04_Volume_Price_Actual.csv")
va = va[va.period == PERIOD]
vb = pd.read_excel(DATA / "02_Budget_FY2026.xlsx", sheet_name="Budget_Drivers")
vb = vb[vb.period == PERIOD]
j = va.merge(vb, on=["store", "period", "category"], how="outer").fillna(0)
vol_effect = ((j.units - j.budget_units) * j.budget_price).sum()
price_effect = ((j.avg_price - j.budget_price) * j.units).sum()

payload = {
    "period": PERIOD,
    "revenue": {
        "actual_m": round(revenue_a / 1e6),
        "budget_m": round(revenue_b / 1e6),
        "var_m": round((revenue_a - revenue_b) / 1e6),
        "var_pct": round(100 * (revenue_a - revenue_b) / revenue_b, 1),
    },
    "gross_margin_pct": {"actual": round(gm_a, 1), "budget": round(gm_b, 1)},
    "ebit": {
        "actual_m": round(ebit_a / 1e6),
        "budget_m": round(ebit_b / 1e6),
        "var_m": round((ebit_a - ebit_b) / 1e6),
        "var_pct": round(100 * (ebit_a - ebit_b) / ebit_b, 1),
    },
    "revenue_bridge": {
        "volume_effect_m": round(vol_effect / 1e6),
        "price_effect_m": round(price_effect / 1e6),
    },
    "top_store_misses": [
        {"store": s, "var_m": int(v)} for s, v in by_store_m.head(3).items()
    ],
    "top_store_beats": [
        {"store": s, "var_m": int(v)} for s, v in by_store_m.tail(3)[::-1].items()
    ],
}

Path("variance_payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
print(json.dumps(payload, indent=2, ensure_ascii=False))