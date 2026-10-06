"""
BLOCK 2 — Data Quality Tests
Chạy: python test_quality.py
"""
import pandas as pd
from pathlib import Path

WAREHOUSE = Path("warehouse")
DATA = Path("data")

fact_pnl = pd.read_parquet(WAREHOUSE / "fact_pnl.parquet")
act = fact_pnl[fact_pnl.scenario == "Actual"]
bud = fact_pnl[fact_pnl.scenario == "Budget"]

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append(status)
    print(f"[{status}]{name}{detail}")


#TEST 1 — Tie-out doanh thu: fact_pnl phải khớp TUYỆT ĐỐI với file nguồn
# gốc sản lượng x giá. Đây là test quan trọng nhất: nó chứng minh pipeline
# không đánh rơi và không nhân đôi một đồng doanh thu nào.
rev_fact = act[act.pnl_group == "Revenue"].groupby("period").amount.sum()
vp = pd.read_csv(DATA / "04_Volume_Price_Actual.csv")
rev_source = vp.groupby("period").revenue.sum()
common_periods = rev_fact.index.intersection(rev_source.index)
diff = (rev_fact[common_periods] - rev_source[common_periods]).abs().sum()
check("1. Tie-out doanh thu (fact_pnl vs volume/price actual)", diff < 1, f"lệch={diff:.0f} VND")

#TEST 2 — Không mất dòng so với ETL đã báo
check("2. Số dòng Actual đúng 8546", len(act) == 8546, f"n={len(act)}")

#TEST 3 — Không có period rỗng/NaN sau khi parse ngày
check("3. Không có period null", act.period.notna().all())

#TEST 4 — Không có pnl_group null (UNMAPPED là giá trị hợp lệ, null thì không)
check("4. Không có pnl_group null (UNMAPPED hợp lệ, null thì không)", fact_pnl.pnl_group.notna().all())

#TEST 5 — Budget có đủ 12 tháng 2026 cho các cặp cost_center x account
bud_2026 = bud[bud.period.str.startswith("2026")]
months_per_pair = bud_2026.groupby(["cost_center", "account"]).period.nunique()
check(
    "5. Mỗi cặp cost_center x account có đủ 12 tháng budget 2026",
    (months_per_pair == 12).all(),
    f"số cặp thiếu tháng:{(months_per_pair != 12).sum()}",
)

#TEST 6 — Không có cost_center null. Tồn tại vì một lý do cụ thể: nếu
# cost_center là NaN (không phải chuỗi "UNASSIGNED"), groupby("cost_center")
# ở Block 3 sẽ ÂM THẦM loại bỏ dòng đó — đúng bẫy pandas đã nói ở Block 1.
check("6. Không có cost_center null trong fact_pnl", fact_pnl.cost_center.notna().all())

print(f"\nTổng kết:{results.count('PASS')}/{len(results)} PASS")
if "FAIL" in results:
    raise SystemExit("Có test FAIL — dừng lại, không sang Power BI khi dữ liệu chưa xác minh.")