"""Customer account statement (گردش حساب) from KOL rows, reference §3.

Balance = Σ credit (Bes) − Σ debit (Bed): negative = the customer owes the shop.
"""
from __future__ import annotations

#: KOL.Va codes with a known meaning; anything else is shown as a generic document.
KIND_LABELS = {"f": "فاکتور فروش"}
DEFAULT_KIND = "سند"
MAX_DESCRIPTION = 60


def side_of(balance: float) -> str:
    if abs(balance) < 0.5:
        return "zero"
    return "debtor" if balance < 0 else "creditor"


def build_statement(data: dict, page: int, page_size: int) -> dict:
    """Newest first, paginated, with the running balance after every row."""
    rows = data.get("rows") or []
    balance = float(data.get("total_credit", 0)) - float(data.get("total_debit", 0))
    # Rows older than the ones read are carried over as an opening balance.
    running = balance - sum(r["credit"] - r["debit"] for r in rows)
    items = []
    for row in rows:
        running += row["credit"] - row["debit"]
        items.append({
            "date": row["date"],
            "kind": KIND_LABELS.get(row["kind"], DEFAULT_KIND),
            "doc_no": row["doc_no"],
            "debit": row["debit"],
            "credit": row["credit"],
            "balance": abs(running),
            "side": side_of(running),
            "description": row["description"][:MAX_DESCRIPTION],
        })
    items.reverse()
    start = (page - 1) * page_size
    return {
        "balance": abs(balance),
        "side": side_of(balance),
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "items": items[start:start + page_size],
    }


def build_full_statement(data: dict, max_rows: int) -> dict:
    """The whole statement for the PDF (v2.6.0): oldest row first, the running
    balance after every row, the opening balance carried over from older rows
    (only the newest ``max_rows`` are read), the sums of the listed rows and the
    final balance with its side."""
    rows = data.get("rows") or []
    balance = float(data.get("total_credit", 0)) - float(data.get("total_debit", 0))
    opening = balance - sum(r["credit"] - r["debit"] for r in rows)
    running = opening
    out = []
    for row in rows:
        running += row["credit"] - row["debit"]
        out.append({
            "date": row["date"],
            "kind": KIND_LABELS.get(row["kind"], DEFAULT_KIND),
            "doc_no": row["doc_no"],
            "description": row["description"][:200],
            "debit": row["debit"],
            "credit": row["credit"],
            "balance": abs(running),
            "side": side_of(running),
        })
    dates = [r["date"] for r in out if r["date"]]
    return {
        "from_date": min(dates) if dates else "",
        "to_date": max(dates) if dates else "",
        "opening_balance": abs(opening),
        "opening_side": side_of(opening),
        "rows": out,
        "total_debit": sum(r["debit"] for r in rows),
        "total_credit": sum(r["credit"] for r in rows),
        "balance": abs(balance),
        "side": side_of(balance),
        "truncated": len(rows) >= max_rows,
    }
