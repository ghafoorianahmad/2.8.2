"""Price lists, rows and mappings in our own SQLite (tables in ``db_own.SCHEMA``).

Shares the OwnDB connection and lock: every method here runs under
``db._lock`` like OwnDB's own methods.
"""
from __future__ import annotations

from ..db_own import OwnDB
from ..util import now_iso
from .matching import part_code

LIST_STATUSES = ("active", "held", "rejected", "superseded", "failed")
_LIST_COLUMNS = (
    "id, list_date, sha256, source, source_ref, posted_at, status, reason, row_count, "
    "file_name, created_at, activated_at, decided_at, decided_by"
)


class PriceListRepo:
    def __init__(self, db: OwnDB):
        self.db = db

    # ---- lists ----------------------------------------------------------
    def get_list(self, list_id: int) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                f"SELECT {_LIST_COLUMNS} FROM price_lists WHERE id=?", (int(list_id),)
            )

    def get_by_sha(self, sha256: str) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                f"SELECT {_LIST_COLUMNS} FROM price_lists WHERE sha256=?", (sha256,)
            )

    def active_list(self) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                f"SELECT {_LIST_COLUMNS} FROM price_lists WHERE status='active' "
                "ORDER BY id DESC LIMIT 1"
            )

    def latest_list(self) -> dict | None:
        """Newest list with rows (active or held): the one rows are mapped from."""
        with self.db._lock:
            return self.db._fetchone(
                f"SELECT {_LIST_COLUMNS} FROM price_lists WHERE status IN ('active','held') "
                "ORDER BY id DESC LIMIT 1"
            )

    def list_lists(self, limit: int = 50) -> list[dict]:
        with self.db._lock:
            return self.db._fetchall(
                f"SELECT {_LIST_COLUMNS} FROM price_lists ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )

    def insert_list(
        self, *, list_date: str, sha256: str, source: str, source_ref: str,
        posted_at: str | None, status: str, reason: str, rows: list[dict],
        file_name: str | None = None,
    ) -> int:
        with self.db._lock:
            ts = now_iso()
            cur = self.db._conn.execute(
                "INSERT INTO price_lists (list_date, sha256, source, source_ref, posted_at, "
                "status, reason, row_count, file_name, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (list_date, sha256, source, source_ref, posted_at, status, reason,
                 len(rows), file_name, ts),
            )
            list_id = cur.lastrowid
            self.db._conn.executemany(
                "INSERT INTO price_list_rows (list_id, row_key, block, section, description, "
                "kind, color, naghd, raval, price_rial) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (list_id, r["row_key"], r["block"], r["section"], r["description"],
                     r["kind"], r["color"], r["naghd"], r["raval"], r["price_rial"])
                    for r in rows
                ],
            )
            self.db._commit()
            return list_id

    def fill_list(self, list_id: int, *, list_date: str, status: str, reason: str,
                  rows: list[dict]) -> None:
        """v2.13.0 «خواندن دوباره»: a list that failed before, now read: its rows,
        date and status (same record, same file)."""
        with self.db._lock:
            self.db._conn.execute("DELETE FROM price_list_rows WHERE list_id=?", (int(list_id),))
            self.db._conn.execute(
                "UPDATE price_lists SET list_date=?, status=?, reason=?, row_count=? WHERE id=?",
                (list_date, status, reason, len(rows), int(list_id)))
            self.db._conn.executemany(
                "INSERT INTO price_list_rows (list_id, row_key, block, section, description, "
                "kind, color, naghd, raval, price_rial) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(int(list_id), r["row_key"], r["block"], r["section"], r["description"],
                  r["kind"], r["color"], r["naghd"], r["raval"], r["price_rial"]) for r in rows])
            self.db._commit()

    def set_reason(self, list_id: int, reason: str) -> None:
        with self.db._lock:
            self.db._conn.execute("UPDATE price_lists SET reason=? WHERE id=?",
                                  (reason, int(list_id)))
            self.db._commit()

    def set_file_name(self, list_id: int, file_name: str) -> None:
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE price_lists SET file_name=? WHERE id=?", (file_name, int(list_id))
            )
            self.db._commit()

    def activate(self, list_id: int, actor: str = "") -> None:
        """Make one list the active one; the previous active list is superseded."""
        with self.db._lock:
            ts = now_iso()
            self.db._conn.execute(
                "UPDATE price_lists SET status='superseded' WHERE status='active' AND id<>?",
                (int(list_id),),
            )
            self.db._conn.execute(
                "UPDATE price_lists SET status='active', activated_at=?, "
                "decided_at=COALESCE(decided_at, CASE WHEN ?<>'' THEN ? END), "
                "decided_by=CASE WHEN ?<>'' THEN ? ELSE decided_by END WHERE id=?",
                (ts, actor, ts, actor, actor, int(list_id)),
            )
            self.db._commit()

    def set_status(self, list_id: int, status_value: str, actor: str = "",
                   reason: str | None = None) -> None:
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE price_lists SET status=?, decided_at=?, decided_by=?, "
                "reason=COALESCE(?, reason) WHERE id=?",
                (status_value, now_iso(), actor, reason, int(list_id)),
            )
            self.db._commit()

    # ---- rows ------------------------------------------------------------
    def rows(self, list_id: int) -> list[dict]:
        with self.db._lock:
            return self.db._fetchall(
                "SELECT r.row_key, r.block, r.section, r.description, r.kind, r.color, "
                "r.naghd, r.raval, r.price_rial, r.price_flag, r.flag_note, r.raval_estimated, "
                "r.orig_naghd, r.orig_raval, r.orig_price_rial, r.pending_naghd, r.pending_raval, "
                "r.pending_price_rial, r.pending_estimated, r.pending_source, "
                "m.id AS mapping_id, m.action, m.kala_code, "
                "m.color_label, COALESCE(m.auto, 0) AS auto, COALESCE(m.auto_reason, '') "
                "AS auto_reason FROM price_list_rows r "
                "LEFT JOIN price_mappings m ON m.row_key = r.row_key "
                "WHERE r.list_id=? ORDER BY r.block, r.rowid",
                (int(list_id),),
            )

    def held_rows(self, list_id: int) -> list[dict]:
        """v2.9.1: rows whose new price waits for a manager (price guard)."""
        return [r for r in self.rows(list_id) if r.get("pending_price_rial") is not None]

    def rows_by_key(self, list_id: int) -> dict[str, dict]:
        return {r["row_key"]: r for r in self.rows(list_id)}

    # ---- mappings -----------------------------------------------------------
    def get_mapping(self, mapping_id: int) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                "SELECT * FROM price_mappings WHERE id=?", (int(mapping_id),)
            )

    def mapping_for_key(self, row_key: str) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                "SELECT * FROM price_mappings WHERE row_key=?", (row_key,)
            )

    def list_mappings(self) -> list[dict]:
        with self.db._lock:
            return self.db._fetchall(
                "SELECT * FROM price_mappings ORDER BY action, kala_code, section, description"
            )

    def mapped_keys(self) -> set[str]:
        with self.db._lock:
            rows = self.db._fetchall("SELECT row_key FROM price_mappings WHERE action='map'")
        return {r["row_key"] for r in rows}

    def upsert_mapping(
        self, *, row_key: str, action: str, kala_code: int | None, color_label: str,
        section: str, description: str, kind: str, color: str, actor: str,
        auto: bool = False, auto_reason: str = "",
    ) -> dict:
        """A staff decision (``auto=False``) also clears an earlier undo of the
        automatic match for the row; an automatic one is flagged for review."""
        with self.db._lock:
            ts = now_iso()
            self.db._conn.execute(
                "INSERT INTO price_mappings (row_key, action, kala_code, color_label, section, "
                "description, kind, color, created_at, updated_at, updated_by, auto, "
                "auto_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(row_key) DO UPDATE "
                "SET action=excluded.action, kala_code=excluded.kala_code, "
                "color_label=excluded.color_label, updated_at=excluded.updated_at, "
                "updated_by=excluded.updated_by, auto=excluded.auto, "
                "auto_reason=excluded.auto_reason",
                (row_key, action, kala_code, color_label, section, description, kind, color,
                 ts, ts, actor, int(bool(auto)), auto_reason if auto else ""),
            )
            if not auto:
                self.db._conn.execute("DELETE FROM price_auto_rejects WHERE row_key=?",
                                      (row_key,))
            self.db._commit()
            return self.mapping_for_key(row_key)

    def confirm_mapping(self, mapping_id: int, actor: str) -> dict | None:
        """Staff accept an automatic decision: it becomes an ordinary one."""
        with self.db._lock:
            self.db._conn.execute(
                "UPDATE price_mappings SET auto=0, auto_reason='', updated_at=?, updated_by=? "
                "WHERE id=?", (now_iso(), actor, int(mapping_id)))
            self.db._commit()
            return self.get_mapping(mapping_id)

    def reject_auto(self, row_key: str, actor: str) -> None:
        """Never match this row automatically again (it stays undecided)."""
        with self.db._lock:
            self.db._conn.execute(
                "INSERT OR IGNORE INTO price_auto_rejects (row_key, created_at, created_by) "
                "VALUES (?,?,?)", (row_key, now_iso(), actor))
            self.db._commit()

    def auto_rejected_keys(self) -> set[str]:
        with self.db._lock:
            return {r["row_key"] for r in self.db._fetchall(
                "SELECT row_key FROM price_auto_rejects")}

    def delete_mapping(self, mapping_id: int) -> bool:
        with self.db._lock:
            cur = self.db._conn.execute(
                "DELETE FROM price_mappings WHERE id=?", (int(mapping_id),)
            )
            self.db._commit()
            return cur.rowcount > 0

    def priced_codes(self) -> set[int]:
        """Products priced from the list: every product with a 'map' mapping."""
        with self.db._lock:
            rows = self.db._fetchall(
                "SELECT DISTINCT kala_code FROM price_mappings WHERE action='map'"
            )
        return {int(r["kala_code"]) for r in rows}

    def variants(self, list_id: int | None, codes: set[int] | None = None) -> dict[int, list[dict]]:
        """kala_code -> colors from the given (active) list. Mapped rows only:
        unmapped or ignored rows never reach a customer."""
        if list_id is None:
            return {}
        with self.db._lock:
            rows = self.db._fetchall(
                "SELECT m.id, m.kala_code, m.color_label, r.color, r.price_rial, "
                "r.pending_price_rial, r.description, r.kind "
                "FROM price_mappings m JOIN price_list_rows r "
                "ON r.row_key = m.row_key AND r.list_id = ? "
                "WHERE m.action = 'map' ORDER BY m.kala_code, m.id",
                (int(list_id),),
            )
        out: dict[int, list[dict]] = {}
        for r in rows:
            code = int(r["kala_code"])
            if codes is not None and code not in codes:
                continue
            out.setdefault(code, []).append({
                "id": int(r["id"]),
                "color": (r["color_label"] or r["color"] or "").strip(),
                # v2.6.2: the part / region (ZAA / CHA …) and the type (ویتنام …);
                # the catalogue decides what the customer picks after the color.
                "part_code": part_code(r["description"]),
                "kind": " ".join(str(r["kind"] or "").split()),
                # v2.9.2: never the old price while a new one waits for a manager
                "price_rial": None if r["pending_price_rial"] is not None else r["price_rial"],
                "held": r["pending_price_rial"] is not None,
            })
        return out

    # ---- inquiries ---------------------------------------------------------
    def add_inquiry(self, user_id: int, kala_code: int, mapping_id: int | None,
                    product_name: str, color: str) -> dict:
        with self.db._lock:
            cur = self.db._conn.execute(
                "INSERT INTO inquiries (user_id, kala_code, mapping_id, product_name, color, "
                "created_at) VALUES (?,?,?,?,?,?)",
                (int(user_id), int(kala_code), mapping_id, product_name, color, now_iso()),
            )
            self.db._commit()
            return self.get_inquiry(cur.lastrowid)

    def get_inquiry(self, inquiry_id: int) -> dict | None:
        with self.db._lock:
            return self.db._fetchone(
                "SELECT i.*, u.name AS customer_name FROM inquiries i "
                "JOIN users u ON u.id = i.user_id WHERE i.id=?",
                (int(inquiry_id),),
            )

    def list_inquiries(self, limit: int = 100) -> list[dict]:
        with self.db._lock:
            return self.db._fetchall(
                "SELECT i.*, u.name AS customer_name FROM inquiries i "
                "JOIN users u ON u.id = i.user_id ORDER BY i.id DESC LIMIT ?",
                (int(limit),),
            )
