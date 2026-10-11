r"""Live checks on the local TEST accounting db (never production).

    .\.venv\Scripts\python.exe scripts\live_db_check.py kol      # statement (KOL), read-only
    .\.venv\Scripts\python.exe scripts\live_db_check.py r5       # invoice tracking (R5), read-only
    .\.venv\Scripts\python.exe scripts\live_db_check.py person   # create_person: commits ONE test
                                                                   # person, then deletes it again

Refuses to run unless shopapi/.env points at the local .\SQLEXPRESS test db.
Prints no personal data: only counts, types, codes of our own test row and booleans.
Run it from a normal PowerShell window: inside the Claude app the SQL Server
shared-memory connection is refused ("access denied").
"""
import re, sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.accounting_reader import AccountingReader
from app.accounting_writer import AccountingWriter
from app.statement import build_statement
from app.text import mobile_key

s = Settings.from_env()
server, dbname = s.accounting_server, s.accounting_database
print("server:", server, "| db:", dbname, "| write_enabled:", s.accounting_write_enabled)
assert server.lower() in (r".\sqlexpress", r"localhost\sqlexpress", r"(local)\sqlexpress"), "not the local test server"
assert dbname.lower() in ("hesab5 t", "hesab5"), "not the test db"
mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode not in ("kol", "r5", "person"):
    sys.exit("usage: live_db_check.py kol|r5|person")
r = AccountingReader(s)
w = AccountingWriter(s)
db = r._db()


def q(sql, *p):
    c = r.connection()
    try:
        return c.execute(sql, *p).fetchall()
    finally:
        c.close()


def counts():
    return tuple(q(f"SELECT (SELECT MAX(Code) FROM {db}.dbo.name_mo), (SELECT COUNT(*) FROM {db}.dbo.name_mo), "
                   f"(SELECT COUNT(*) FROM {db}.dbo.taf), (SELECT COUNT(*) FROM {db}.dbo.DetailTBL)")[0])


if mode == "kol":
    for col in q("SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
                 "WHERE TABLE_NAME='KOL' AND COLUMN_NAME IN ('Num_kol','Date1','Va','N_sanad','Bed','Bes','Sharh','Noa','Codkol','Cod_n') ORDER BY COLUMN_NAME"):
        print("  KOL col", tuple(col))
    top = q(f"SELECT TOP 3 Codkol, COUNT(*) n FROM {db}.dbo.KOL WHERE Noa='m' GROUP BY Codkol ORDER BY COUNT(*) DESC")
    for code, n in top:
        data = r.customer_statement(int(code), s.statement_max_rows)
        rows = data["rows"]
        dates_ok = all(re.fullmatch(r"\d{4}/\d{2}/\d{2}", x["date"]) for x in rows)
        asc = all(rows[i]["date"] <= rows[i + 1]["date"] for i in range(len(rows) - 1))
        sums_ok = (abs(sum(x["debit"] for x in rows) - data["total_debit"]) < 0.5
                   and abs(sum(x["credit"] for x in rows) - data["total_credit"]) < 0.5)
        (b, c), = [tuple(x) for x in q(f"SELECT SUM(Bed), SUM(Bes) FROM {db}.dbo.KOL WHERE Noa='m' AND Codkol=? "
                                       f"AND NOT (Va=N'غ' AND Cod_n IN (-1003,-1005))", code)]
        ref_ok = abs(float(b or 0) - data["total_debit"]) < .5 and abs(float(c or 0) - data["total_credit"]) < .5
        kinds = sorted({x["kind"] for x in rows})
        st = build_statement(data, 1, 10)
        last_ok = bool(st["items"]) and abs(st["items"][0]["balance"] - st["balance"]) < .5
        st_small = build_statement(r.customer_statement(int(code), 5), 1, 10)
        trunc_ok = abs(st_small["items"][0]["balance"] - st["balance"]) < .5
        print(f"  person (rows={n}): read={len(rows)} dates_fmt={dates_ok} ascending={asc} row_sums==totals={sums_ok} "
              f"totals==ref_formula={ref_ok} kinds={kinds} newest_running==balance={last_ok} "
              f"truncated(5)_running_ok={trunc_ok} pages={(st['total'] + 9) // 10}")
        types = {k: type(v).__name__ for k, v in rows[0].items()} if rows else {}
        print("   row field types:", types, "| desc max len:", max((len(x['description']) for x in rows), default=0),
              "| fractional amounts:", any(x["debit"] % 1 or x["credit"] % 1 for x in rows))

elif mode == "r5":
    from app.tracking import invoice_state
    cnt = q(f"SELECT COUNT(*) FROM {db}.dbo.KalaOrder")[0][0]
    inv = q(f"SELECT TOP 10 h.Codlp FROM {db}.dbo.KalaOrder h WHERE EXISTS "
            f"(SELECT 1 FROM {db}.dbo.facto f WHERE f.ordercode=h.Codlp) ORDER BY h.Codlp DESC")
    noinv = q(f"SELECT TOP 5 h.Codlp FROM {db}.dbo.KalaOrder h WHERE NOT EXISTS "
              f"(SELECT 1 FROM {db}.dbo.facto f WHERE f.ordercode=h.Codlp) ORDER BY h.Codlp DESC")
    print("  KalaOrder rows:", cnt, "| with invoice (top10):", len(inv), "| without (sample):", len(noinv))
    codes = [int(x[0]) for x in inv + noinv] + [-999999]
    prog = r.invoice_progress(codes)
    for c in codes:
        p = prog.get(c)
        print("   Codlp", c, "->", None if p is None else (p["ordered"], p["invoiced"], invoice_state(p["ordered"], p["invoiced"])))
    for c in [int(x[0]) for x in inv[:3]]:
        lines = q(f"SELECT d.Num, d.Codekala, d.Meg, (SELECT SUM(f.Meg) FROM {db}.dbo.facto f WHERE f.ordercode=d.Codlp_ "
                  f"AND f.orderdetailcode=d.Num AND f.Codekala=d.Codekala) FROM {db}.dbo.KalaOrderDetail d WHERE d.Codlp_=?", c)
        print("   lines", c, [(l[0], l[1], float(l[2] or 0), float(l[3] or 0)) for l in lines])
    print("  facto rows with ordercode>0:", q(f"SELECT COUNT(*) FROM {db}.dbo.facto WHERE ordercode>0")[0][0])
    print("  va values in KalaOrder:", [tuple(x) for x in q(f"SELECT va, COUNT(*) FROM {db}.dbo.KalaOrder GROUP BY va")])

elif mode == "person":
    trig = q(f"SELECT OBJECT_NAME(parent_id) FROM sys.triggers WHERE OBJECT_NAME(parent_id) IN ('name_mo','taf','DetailTBL')")
    print("  triggers on name_mo/taf/DetailTBL:", [t[0] for t in trig])
    ex = q(f"SELECT TOP 50 RIGHT(RTRIM(d.Comment),10) FROM {db}.dbo.DetailTBL d WHERE d.Va=0 AND d.TabaghehBandiID IN (1,3) "
           f"AND LEN(RTRIM(d.Comment)) BETWEEN 10 AND 14 AND RIGHT(RTRIM(d.Comment),10) LIKE '9%'")
    keys = [k[0] for k in ex if mobile_key("0" + k[0])]
    uniq = next((k for k in keys if len(r.person_codes_by_mobile(k)) == 1), None)
    print("  existing mobiles sampled:", len(keys), "| unique one found:", uniq is not None)
    if uniq:
        expect = r.person_codes_by_mobile(uniq)[0]
        c0 = counts()
        res = w.create_person("آزمون", "تکراری", "0" + uniq, dry_run=True)
        print("  duplicate (existing mobile, dry-run): existing=", res.existing, "ambiguous=", res.ambiguous,
              "same code=", res.person_code == expect)
        res = w.create_person("آزمون", "تکراری", "+98" + uniq, dry_run=False)
        print("  duplicate via +98 form, dry_run=False: existing=", res.existing, "committed=", res.committed,
              "| nothing written:", counts() == c0)
    test_mobile = "09990007731"
    assert not r.person_codes_by_mobile(mobile_key(test_mobile)), "test mobile already used"
    before = counts()
    res = w.create_person("آزمون", "شاپ‌بات", test_mobile, address="آزمایشی", dry_run=True)
    print("  dry-run new: code=max+1:", res.person_code == before[0] + 1, "taf set:", res.taf_code is not None,
          "rolled_back:", res.rolled_back, "no rows left:", counts() == before)
    res = w.create_person("آزمون", "شاپ‌بات", test_mobile, address="آزمایشی", dry_run=False)
    code = res.person_code
    print("  real new: committed=", res.committed, "code=max+1:", code == before[0] + 1)
    try:
        row = q(f"SELECT n.Gcod, n.l_gey, n.codetaf, LEN(n.datestart), LEN(n.telephons), t.Cota, t.como, t.codgtaf, t.va "
                f"FROM {db}.dbo.name_mo n JOIN {db}.dbo.taf t ON t.Code=n.codetaf WHERE n.Code=?", code)
        print("   name_mo/taf link (Gcod,l_gey,codetaf,len(date),len(tel),Cota,como,codgtaf,va):", [tuple(x) for x in row],
              "| Cota==Code:", bool(row) and row[0][5] == code)
        det = q(f"SELECT TabaghehBandiID, Va, darfn FROM {db}.dbo.DetailTBL WHERE IDMaster=?", code)
        print("   DetailTBL rows (type,Va,darfn):", [tuple(x) for x in det])
        print("   R4 finds it:", r.person_codes_by_mobile(mobile_key(test_mobile)) == [code],
              "| find_person_by_mobile(+98 spaced):", (r.find_person_by_mobile("+98 999 000 7731") or {}).get("code") == code)
        again = w.create_person("دیگر", "تکراری", "۰۹۹۹۰۰۰۷۷۳۱", dry_run=False)
        print("   second create same phone (Persian digits): existing=", again.existing, "same code=",
              again.person_code == code, "committed=", again.committed)
        print("   name_mo count +1 only:", counts()[1] == before[1] + 1)
    finally:
        c = r.connection()
        c.autocommit = False
        n1 = c.execute(f"DELETE FROM {db}.dbo.DetailTBL WHERE IDMaster=? AND Comment=?", code, test_mobile).rowcount
        n2 = c.execute(f"DELETE FROM {db}.dbo.taf WHERE Cota=? AND codgtaf=59", code).rowcount
        n3 = c.execute(f"DELETE FROM {db}.dbo.name_mo WHERE Code=?", code).rowcount
        c.commit()
        c.close()
        print("  cleanup deleted (DetailTBL,taf,name_mo):", (n1, n2, n3), "| counts restored:", counts() == before)
