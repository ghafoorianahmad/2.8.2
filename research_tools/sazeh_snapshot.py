r"""Before/after snapshot + diff tool for the Sazeh Hesab TEST database.

Usage (use the shopapi venv python, or any python with pyodbc):
    python sazeh_snapshot.py save before            # snapshot now
    ... perform ONE action in the Sazeh Hesab GUI (pointed at the TEST db) ...
    python sazeh_snapshot.py save after
    python sazeh_snapshot.py diff before after      # what the action wrote

Options:  --server ".\\SQLEXPRESS"   --db hesab5     (never point this at production)

Safety: read-only. Personal columns (names, phones, addresses, national IDs, tokens,
SMS credentials) are NEVER printed - they are replaced by a short hash so that a
change is still detected but no value is shown.
"""
import argparse, hashlib, json, os, sys
import pyodbc

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPDIR = os.path.join(HERE, "snapshots")

# table -> (key columns, columns whose VALUE must be masked)
TABLES = {
    "KalaOrder": (["Codlp"], ["Sharhlp"]),
    "KalaOrderDetail": (["Codlp_", "Num"], []),
    "Fact": (["Numfact"], ["Sharh", "Tava"]),
    "Facto": (["Num"], ["Sharh"]),
    "kardex_an": (["Num"], ["Sharh"]),
    "KOL": (["Num_kol"], ["Sharh"]),
    "havale": (["code"], ["sharh"]),
    "Dar": (["Code"], ["Babat"]),
    "Kala": (["Code"], []),
    "Gkala": (["Code"], []),
    "taf": (["Code"], ["Sharh"]),
    "DetailTBL": (["ID"], ["Comment"]),
    "TabaghehBandi": (["code"], ["sharh"]),
    "setting": (["code"], ["name", "share"]),          # values masked: rows 497-499, 648-650 hold credentials
    "Telegram_user": (["Id"], ["FullName", "PhoneNumber", "Name_mo_FullName"]),
    "Telegram_OrderList": (["Id"], []),
    "Telegram_OrderDetails": (["Id"], []),
    "name_mo": (["Code"], ["Name", "fname", "Tel1", "Tel2", "Tel3", "Addres", "Addres2", "mobile", "telephons",
                           "Codemelli", "Numbershenasname", "codeposti", "Namepedar", "email", "web", "memo1",
                           "AccountingNumber", "shenaseMeli", "shomareSabt", "ShomareEghtesadi", "Moaref"]),
}


def connect(args):
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={args.server};DATABASE={args.db};"
          "Trusted_Connection=yes")
    c = pyodbc.connect(cs, autocommit=True)
    c.setdecoding(pyodbc.SQL_CHAR, encoding="cp1256")
    return c


def mask(v):
    if v is None:
        return None
    return "#" + hashlib.sha1(str(v).encode("utf-8", "replace")).hexdigest()[:6] + f"(len {len(str(v))})"


def save(args):
    c = connect(args)
    cur = c.cursor()
    out = {"tables": {}, "counts": {}}
    for t in [r[0] for r in cur.execute("select name from sys.tables order by name").fetchall()]:
        out["counts"][t] = cur.execute(f"select count(*) from [{t}]").fetchone()[0]
    for t, (keys, masked) in TABLES.items():
        lob = {r[0] for r in cur.execute(
            "select c.name from sys.columns c join sys.types y on y.user_type_id=c.user_type_id "
            "where c.object_id=object_id(?) and (y.name in ('text','ntext','image','xml') or c.max_length=-1)", t)}
        cols = [r[0] for r in cur.execute("select name from sys.columns where object_id=object_id(?) order by column_id", t)]
        cols = [x for x in cols if x not in lob or x in masked]
        rows = cur.execute(f"select {','.join('['+x+']' for x in cols)} from [{t}]").fetchall()
        d = {}
        for r in rows:
            rec = {}
            for name, v in zip(cols, r):
                if t == "Telegram_Setting":
                    continue
                if name in masked or name.lower() in {m.lower() for m in masked}:
                    v = mask(v)
                elif isinstance(v, (bytes, bytearray)):
                    v = mask(bytes(v))
                else:
                    v = None if v is None else (float(v) if hasattr(v, "as_tuple") else (str(v) if not isinstance(v, (int, float, str, bool)) else v))
                rec[name] = v
            low = {x.lower(): x for x in rec}
            d["|".join(str(rec[low[k.lower()]]) for k in keys)] = rec
        out["tables"][t] = d
    os.makedirs(SNAPDIR, exist_ok=True)
    with open(os.path.join(SNAPDIR, args.name + ".json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"saved {args.name}: {len(out['counts'])} tables counted, {len(TABLES)} tables dumped (personal values masked)")


def diff(args):
    a = json.load(open(os.path.join(SNAPDIR, args.a + ".json"), encoding="utf-8"))
    b = json.load(open(os.path.join(SNAPDIR, args.b + ".json"), encoding="utf-8"))
    print("== row-count changes (all tables)")
    for t in sorted(b["counts"]):
        if a["counts"].get(t) != b["counts"][t]:
            print(f"  {t}: {a['counts'].get(t)} -> {b['counts'][t]}")
    for t in TABLES:
        ta, tb = a["tables"].get(t, {}), b["tables"].get(t, {})
        added = [k for k in tb if k not in ta]
        removed = [k for k in ta if k not in tb]
        changed = [k for k in tb if k in ta and ta[k] != tb[k]]
        if not (added or removed or changed):
            continue
        print(f"\n== {t}: +{len(added)} added, -{len(removed)} removed, ~{len(changed)} changed")
        for k in added[:15]:
            nn = {c: v for c, v in tb[k].items() if v not in (None, "", 0, 0.0, False)}
            print(f"  + [{k}] non-empty: {json.dumps(nn, ensure_ascii=False)[:1500]}")
            nul = [c for c, v in tb[k].items() if v is None]
            print(f"      NULL columns: {', '.join(nul)[:600]}")
        for k in removed[:15]:
            print(f"  - [{k}]")
        for k in changed[:25]:
            ch = {c: (ta[k].get(c), tb[k].get(c)) for c in tb[k] if ta[k].get(c) != tb[k].get(c)}
            print(f"  ~ [{k}] {json.dumps(ch, ensure_ascii=False)[:800]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--server", default=r".\SQLEXPRESS")
    p.add_argument("--db", default="hesab5")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save"); s.add_argument("name"); s.set_defaults(fn=save)
    d = sub.add_parser("diff"); d.add_argument("a"); d.add_argument("b"); d.set_defaults(fn=diff)
    a = p.parse_args()
    if a.db.lower() not in ("hesab5", "hesab5 t") and "localhost" not in a.server.lower() and not a.server.startswith("."):
        sys.exit("refusing: only local test databases are allowed")
    a.fn(a)
