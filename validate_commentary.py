"""
BLOCK 5c — Guardrail chống hallucination.
Bóc mọi con số trong commentary, đối chiếu với tập số hợp lệ từ JSON.
Xử lý định dạng số kiểu VN: dấu CHẤM = phân cách nghìn, dấu PHẨY = thập phân.
Cách dùng: python validate_commentary.py commentary.txt
"""
import json
import re
import sys
from pathlib import Path

CODE_PATTERN = re.compile(r"\b(ST|HQ)-\d{1,3}\b")
DATE_PATTERN = re.compile(r"\b\d{1,2}/\d{4}\b|\btháng\s+\d{1,2}\b", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
NUMBER_PATTERN = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?%?")


def vn_number_to_float(token: str) -> float:
    s = token.rstrip("%").replace(".", "").replace(",", ".")
    return float(s)


def extract_numbers(text: str) -> list[float]:
    text = CODE_PATTERN.sub(" ", text)
    text = DATE_PATTERN.sub(" ", text)
    text = YEAR_PATTERN.sub(" ", text)
    tokens = NUMBER_PATTERN.findall(text)
    out = []
    for t in tokens:
        try:
            out.append(vn_number_to_float(t))
        except ValueError:
            continue
    return out


def allowed_numbers_from_payload(payload: dict) -> set[float]:
    allowed = set()

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, (int, float)):
            allowed.add(float(obj))
            allowed.add(abs(float(obj)))

    walk(payload)
    return allowed


def main():
    if len(sys.argv) != 2:
        print("Cách dùng: python validate_commentary.py <file_commentary.txt>")
        sys.exit(1)

    commentary = Path(sys.argv[1]).read_text(encoding="utf-8")
    payload = json.loads(Path("variance_payload.json").read_text(encoding="utf-8"))

    found = extract_numbers(commentary)
    allowed = allowed_numbers_from_payload(payload)

    TOL = 0.15
    suspect = [n for n in found if not any(abs(n - a) <= TOL for a in allowed)]

    if suspect:
        print(f"HALLUCINATION DETECTED: các số sau không khớp payload gốc: {sorted(set(suspect))}")
        sys.exit(1)
    else:
        print(f"OK — mọi con số trong commentary ({len(found)} số) đều khớp với payload.")
        sys.exit(0)


if __name__ == "__main__":
    main()