"""Ad-hoc Jalali calendar verification (dev tool, not part of the test suite)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.persian import gregorian_to_jalali as g  # noqa: E402

print("--- Nowruz detection 2015..2030 ---")
for year in range(2015, 2031):
    for day in range(19, 23):
        if g(year, 3, day)[1:] == (1, 1):
            print(f"{year}: Nowruz = 3/{day}")
            break
    else:
        print(f"{year}: NOT FOUND")

print("--- anchors ---")
anchors = [
    ((2020, 3, 20), (1399, 1, 1)),
    ((2021, 3, 21), (1400, 1, 1)),
    ((2022, 3, 21), (1401, 1, 1)),
    ((2023, 3, 21), (1402, 1, 1)),
    ((2024, 3, 20), (1403, 1, 1)),
    ((2025, 3, 21), (1404, 1, 1)),
    ((2026, 3, 21), (1405, 1, 1)),
    ((2025, 1, 1), (1403, 10, 12)),
    ((2024, 12, 31), (1403, 10, 11)),
    ((2025, 3, 21), (1404, 1, 1)),
    ((2026, 2, 19), (1404, 11, 30)),
]
bad = 0
for greg, expected in anchors:
    got = g(*greg)
    ok = got == expected
    bad += 0 if ok else 1
    print(f"{greg} -> {got} {'OK' if ok else f'MISMATCH expected {expected}'}")
print("mismatches:", bad)
