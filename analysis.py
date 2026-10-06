"""
BLOCK 3 — P&L, Variance theo cửa hàng, Bridge Giá/Lượng cho kỳ 2026-09
Chạy: python analysis.py
"""
import pandas as pd
from pathlib import Path

WAREHOUSE = Path("warehouse")
DATA = Path("data")
PERIOD = "2026-09"

fact_pnl = pd.read_parquet(WAREHOUSE / "fact_pnl.parquet")
dim_costcenter = pd.read_parquet(WAREHOUSE / "dim_costcenter.parquet")

# ---------------------------------------------------------------------------
# (a) P&L Actual vs Budget — tháng 2026-09
# ---------------------------------------------------------------------------
cur = fact_pnl[fact_pnl.period == PERIOD]
pl = cur.groupby(["pnl_group", "scenario"]).amount.sum().unstack("scenario").fillna(0)
pl["Var"] = pl.get("Actual", 0) - pl.get("Budget", 0)

ORDER = ["Revenue", "COGS", "Store Opex", "G&A", "UNMAPPED", "D&A", "Below EBIT"]
pl = pl.reindex(ORDER)

print(f"=== (a) P&L{PERIOD}, VND triệu ===")
print((pl / 1e6).round(0).to_string())

revenue = pl.loc["Revenue", "Actual"]
budget_revenue = pl.loc["Revenue", "Budget"]
cogs = pl.loc["COGS", "Actual"]
budget_cogs = pl.loc["COGS", "Budget"]
gross_margin_pct = 100 * (revenue - cogs) / revenue
budget_gm_pct = 100 * (budget_revenue - budget_cogs) / budget_revenue

opex_lines = ["Store Opex", "G&A", "UNMAPPED", "D&A"]
ebit_actual = revenue - cogs - pl.loc[opex_lines, "Actual"].sum()
ebit_budget = budget_revenue - budget_cogs - pl.loc[opex_lines, "Budget"].sum()

print(f"\nRevenue   Actual{revenue/1e6:,.0f}  Budget{budget_revenue/1e6:,.0f}  "
      f"Var{(revenue-budget_revenue)/1e6:+,.0f} ({100*(revenue-budget_revenue)/budget_revenue:+.1f}%)")
print(f"Gross Margin %   Actual{gross_margin_pct:.1f}%  Budget{budget_gm_pct:.1f}%")
print(f"EBIT      Actual{ebit_actual/1e6:,.0f}  Budget{ebit_budget/1e6:,.0f}  "
      f"Var{(ebit_actual-ebit_budget)/1e6:+,.0f}")

# ---------------------------------------------------------------------------
# (b) Variance doanh thu theo cửa hàng
#
#   !! LƯU Ý: "UNASSIGNED" sẽ xuất hiện trong bảng dưới với số dương lớn.
#      Đây CHÍNH LÀ hệ quả của quyết định ở Block 1 (40 dòng cost_center
#      rỗng gán vào UNASSIGNED). Doanh thu đó rất có thể thuộc về ST-01
#      (thấy rõ nếu so Checkpoint 3b với bridge ở phần c). Đừng báo cáo
#      "UNASSIGNED beat kế hoạch" cho sếp — đây là lỗi dữ liệu cần ghi
#      chú, không phải một kết quả kinh doanh thật.
#      >>> HÃY HỎI Ý AI: nếu bắt buộc phải nộp báo cáo hôm nay mà chưa
#          kịp truy lại 40 dòng đó thuộc cửa hàng nào, nên trình bày
#          dòng UNASSIGNED trong báo cáo như thế nào để không gây hiểu
#          lầm cho người đọc?
# ---------------------------------------------------------------------------
rev_cur = cur[cur.pnl_group == "Revenue"]
by_store = rev_cur.groupby(["cost_center", "scenario"]).amount.sum().unstack("scenario").fillna(0)
by_store["Var"] = by_store.get("Actual", 0) - by_store.get("Budget", 0)
by_store = by_store.merge(dim_costcenter[["cost_center", "store_name"]], on="cost_center", how="left")
by_store = by_store.sort_values("Var")

print(f"\n=== (b) Variance doanh thu theo cửa hàng{PERIOD}, VND triệu ===")
print((by_store.set_index("cost_center")[["Var"]] / 1e6).round(0).to_string())

# ---------------------------------------------------------------------------
# (c) Bridge Giá / Lượng — dùng 04_Volume_Price_Actual.csv + Budget_Drivers
#
#   Volume effect = (Units_actual - Units_budget) x Price_budget
#   Price  effect = (Price_actual  - Price_budget) x Units_actual
# ---------------------------------------------------------------------------
va = pd.read_csv(DATA / "04_Volume_Price_Actual.csv")
va = va[va.period == PERIOD]

vb = pd.read_excel(DATA / "02_Budget_FY2026.xlsx", sheet_name="Budget_Drivers")
vb = vb[vb.period == PERIOD]

j = va.merge(vb, on=["store", "period", "category"], how="outer").fillna(0)
j["vol_effect"] = (j.units - j.budget_units) * j.budget_price
j["price_effect"] = (j.avg_price - j.budget_price) * j.units

print(f"\n=== (c) Bridge doanh thu{PERIOD}, VND triệu ===")
print("Budget revenue   :", round(j.budget_revenue.sum() / 1e6))
print("Volume effect    :", f"{j.vol_effect.sum()/1e6:+,.0f}")
print("Price effect     :", f"{j.price_effect.sum()/1e6:+,.0f}")
print("Actual revenue   :", round(j.revenue.sum() / 1e6))
residual = j.revenue.sum() - j.budget_revenue.sum() - j.vol_effect.sum() - j.price_effect.sum()
print(f"Residual check   :{residual/1e6:+,.1f}  (phải ~ 0, lệch nhỏ do làm tròn giá)")

print("\nTheo nhóm hàng (VND triệu):")
by_cat = j.groupby("category")[["budget_revenue", "vol_effect", "price_effect", "revenue"]].sum() / 1e6
print(by_cat.round(0).to_string())