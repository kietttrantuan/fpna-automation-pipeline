"""
BLOCK 1 — ETL: data/ (4 file bẩn) -> warehouse/ (4 file parquet sạch, dạng star schema)
"""
import time
import pandas as pd
from pathlib import Path

t0 = time.perf_counter()

DATA = Path("data")
WAREHOUSE = Path("warehouse")
WAREHOUSE.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# BƯỚC 1 — Đọc GL thô, xóa dòng trùng
# ---------------------------------------------------------------------------
gl = pd.read_csv(DATA / "01_GL_transactions_raw.csv")
key_cols = [c for c in gl.columns if c != "line_id"]
n_before = len(gl)
gl = gl.drop_duplicates(subset=key_cols).reset_index(drop=True)
print(f"[1] GL rows:{n_before} ->{len(gl)} (xóa{n_before - len(gl)} dòng trùng)")

# ---------------------------------------------------------------------------
# BƯỚC 2 — amount_vnd: một số dòng là text "1,234,567" -> ép về số
# ---------------------------------------------------------------------------
gl["amount"] = (
    gl["amount_vnd"].astype(str).str.replace(",", "", regex=False).astype(float)
)

# ---------------------------------------------------------------------------
# BƯỚC 3 — account_name: TRIM + chuẩn hóa hoa/thường về một dạng duy nhất
# ---------------------------------------------------------------------------
gl["account"] = gl["account_name"].str.strip().str.title().str.replace("Cogs", "COGS")

# ---------------------------------------------------------------------------
# BƯỚC 4 — cost_center: TRIM; "ST-7" -> "ST-07"; rỗng -> "UNASSIGNED"
#
#   !! BẪY PANDAS THẬT (gặp đúng lúc build project này, không phải lý
#      thuyết suông): .astype(str) trên một cột có giá trị NaN không
#      luôn luôn ra chuỗi "nan". Với dtype string mới của pandas 3.x,
#      NaN có thể vẫn ở lại là null sau .astype(str). Nếu code chỉ
#      .replace({"nan": ...}) để bắt NaN thì NHỮNG DÒNG NÀY BỊ BỎ SÓT
#      lặng lẽ — không lỗi gì cả, nhưng khi groupby("cost_center") ở
#      Block 3, pandas tự động loại nhóm NaN ra khỏi kết quả -> mất
#      doanh thu một cách vô hình, tổng P&L vẫn khớp (vì tổng không qua
#      groupby theo cost_center) nhưng báo cáo theo cửa hàng thì sai.
#      Cách an toàn: luôn .fillna("") TRƯỚC khi .astype(str).
#
#   !! QUYẾT ĐỊNH NGHIỆP VỤ: 40 dòng cost_center rỗng gán hết vào
#      "UNASSIGNED" thay vì cố đoán cửa hàng nào. Chạy xong Block 3,
#      anh sẽ thấy "UNASSIGNED" xuất hiện trong top beats với +135
#      triệu — đây gần như chắc chắn là doanh thu thật của một cửa
#      hàng nào đó bị thất lạc do GL gốc bỏ trống cost_center.
#      >>> HÃY HỎI Ý AI: trong tình huống GL thật gặp đúng việc này,
#          nên gán theo document_no (số chứng từ có thể trace ngược),
#          theo memo, hay báo cáo riêng cho kế toán xử lý tay? Mỗi
#          phương án đánh đổi gì giữa tốc độ xử lý và độ chính xác?
# ---------------------------------------------------------------------------
cc = gl["cost_center"].fillna("").astype(str).str.strip()
cc = cc.replace("", "UNASSIGNED")
cc = cc.str.replace(r"^ST-(\d)$", lambda m: "ST-0" + m.group(1), regex=True)
gl["cost_center"] = cc

# ---------------------------------------------------------------------------
# BƯỚC 5 — posting_date: 3 định dạng lẫn lộn -> parse -> cột period "YYYY-MM"
# ---------------------------------------------------------------------------
gl["posting_date_parsed"] = pd.to_datetime(
    gl["posting_date"], format="mixed", dayfirst=True
)
gl["period"] = gl["posting_date_parsed"].dt.to_period("M").astype(str)

max_period = gl["period"].max()
assert max_period == "2026-09", (
    f"BẪY NGÀY THÁNG: period.max() ={max_period}, phải là 2026-09. "
    "Có dòng bị parse sai tháng/năm — kiểm tra lại dayfirst."
)
print(f"[5] Max period:{max_period}  (đúng)")

# ---------------------------------------------------------------------------
# BƯỚC 6 — Nối COA lấy pnl_group; tài khoản thiếu COA -> pnl_group = "UNMAPPED"
#
#   !! QUYẾT ĐỊNH NGHIỆP VỤ: 3 tài khoản thiếu trong COA có thể (a) bổ
#      sung thủ công vào COA ngay, hay (b) giữ UNMAPPED và báo cáo riêng
#      cho controller xác nhận nhóm P&L đúng trước khi đưa vào báo cáo
#      chính thức. Project này chọn (b) để minh họa pipeline không bao
#      giờ ÂM THẦM loại bỏ dữ liệu khi gặp lỗi mapping.
#      >>> HÃY HỎI Ý AI: phương án nào an toàn hơn cho một pipeline chạy
#          tự động hàng tháng không có người rà soát trước khi publish?
# ---------------------------------------------------------------------------
coa = pd.read_excel(DATA / "03_Master_Data.xlsx", sheet_name="Chart_of_Accounts")
coa["account"] = coa["account_name"].str.strip().str.title().str.replace("Cogs", "COGS")

gl = gl.merge(
    coa[["account", "pnl_group", "sub_group", "pnl_order"]], on="account", how="left"
)
is_unmapped = gl["pnl_group"].isna()
unmapped_accounts = sorted(gl.loc[is_unmapped, "account"].unique())
gl["pnl_group"] = gl["pnl_group"].fillna("UNMAPPED")
gl["sub_group"] = gl["sub_group"].fillna(gl["account"])
print(f"[6] Dòng UNMAPPED:{is_unmapped.sum()} | Tài khoản thiếu COA:{unmapped_accounts}")

# ---------------------------------------------------------------------------
# BƯỚC 7 — Quy ước dấu: revenue ghi DƯƠNG trong fact_pnl
#          (GL gốc ghi ÂM cho doanh thu, chi phí ghi DƯƠNG sẵn -> chỉ đảo
#          dấu riêng dòng Revenue, các dòng chi phí giữ nguyên)
# ---------------------------------------------------------------------------
gl["amount_signed"] = gl["amount"] * gl["pnl_group"].map(lambda g: -1 if g == "Revenue" else 1)
# EBIT = Revenue - COGS - Store Opex - G&A - UNMAPPED - D&A

fact_actual = gl[["period", "cost_center", "account", "pnl_group", "amount_signed"]].rename(
    columns={"amount_signed": "amount"}
)
fact_actual["scenario"] = "Actual"

# ---------------------------------------------------------------------------
# BƯỚC 8 — Budget: unpivot từ wide (12 cột tháng) sang long, scenario="Budget"
# ---------------------------------------------------------------------------
bw = pd.read_excel(DATA / "02_Budget_FY2026.xlsx", sheet_name="Budget_by_Month")
budget_long = bw.melt(
    id_vars=["cost_center", "account_name"], var_name="period_label", value_name="budget_amount"
)
budget_long["period"] = pd.to_datetime(
    budget_long["period_label"], format="%b-%y"
).dt.to_period("M").astype(str)
budget_long["account"] = (
    budget_long["account_name"].str.strip().str.title().str.replace("Cogs", "COGS")
)
budget_long = budget_long.merge(coa[["account", "pnl_group"]], on="account", how="left")
budget_long["pnl_group"] = budget_long["pnl_group"].fillna("UNMAPPED")
# Cùng quy ước dấu với Actual: budget gốc cũng ghi âm cho Revenue
budget_long["amount_signed"] = budget_long["budget_amount"] * budget_long["pnl_group"].map(
    lambda g: -1 if g == "Revenue" else 1
)

fact_budget = budget_long.rename(columns={"amount_signed": "amount"})[
    ["period", "cost_center", "account", "pnl_group", "amount"]
]
fact_budget["scenario"] = "Budget"

fact_pnl = pd.concat([fact_actual, fact_budget], ignore_index=True)

# ---------------------------------------------------------------------------
# Dim tables
# ---------------------------------------------------------------------------
dim_account = coa[["account", "pnl_group", "sub_group", "pnl_order"]].drop_duplicates()

store_master = pd.read_excel(DATA / "03_Master_Data.xlsx", sheet_name="Store_Master")
dim_costcenter = store_master.rename(columns={"store_code": "cost_center"})[
    ["cost_center", "store_name", "region", "format", "open_date"]
]
dim_costcenter = pd.concat(
    [
        dim_costcenter,
        pd.DataFrame([
            {"cost_center": "HQ", "store_name": "Head Office", "region": "HQ",
             "format": "HQ", "open_date": None},
            {"cost_center": "UNASSIGNED", "store_name": "Unassigned", "region": "Unknown",
             "format": "Unknown", "open_date": None},
        ]),
    ],
    ignore_index=True,
)

periods = sorted(fact_pnl["period"].unique())
dim_date = pd.DataFrame({"period": periods})
dim_date["year"] = dim_date["period"].str[:4].astype(int)
dim_date["month"] = dim_date["period"].str[5:7].astype(int)
dim_date["month_name"] = pd.to_datetime(dim_date["period"] + "-01").dt.strftime("%b")
dim_date["quarter"] = ((dim_date["month"] - 1) // 3 + 1).map(lambda q: f"Q{q}")

# ---------------------------------------------------------------------------
# Ghi parquet
# ---------------------------------------------------------------------------
fact_pnl.to_parquet(WAREHOUSE / "fact_pnl.parquet", index=False)
dim_account.to_parquet(WAREHOUSE / "dim_account.parquet", index=False)
dim_costcenter.to_parquet(WAREHOUSE / "dim_costcenter.parquet", index=False)
dim_date.to_parquet(WAREHOUSE / "dim_date.parquet", index=False)

elapsed = time.perf_counter() - t0

# ---------------------------------------------------------------------------
# CHECKPOINT 1
# ---------------------------------------------------------------------------
act = fact_pnl[fact_pnl.scenario == "Actual"]
print("\n=== CHECKPOINT 1 ===")
print("Rows (Actual) sau dedup :", len(act), " (phải = 8546)")
print("Số kỳ (period)          :", act.period.nunique(), " (phải = 21)")
print("Số tài khoản            :", act.account.nunique(), " (phải = 22)")
print("Số cost_center          :", act.cost_center.nunique(), " (phải = 14, gồm cả UNASSIGNED)")
print("Max period              :", act.period.max(), " (phải = 2026-09)")
print(f"\nThời gian chạy ETL:{elapsed:.2f} giây")