# Verified write recipes (SQL Server 2008 R2 compatible T-SQL). Executed with pyodbc, explicit transaction.
W_LOCK = "DECLARE @r int; EXEC @r = sp_getapplock @Resource=?, @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=15000; SELECT @r"

def create_person(cur, first_name, last_name, mobile_digits, address=None, gcod=4):
    """Returns (person_code, taf_code). Caller owns the transaction (autocommit=False)."""
    cur.execute(W_LOCK, 'shop:name_mo'); assert cur.fetchone()[0] >= 0
    cur.execute("SELECT ISNULL(MAX(Code),0)+1 FROM dbo.name_mo"); code = cur.fetchone()[0]
    cur.execute("SELECT dbo.MiladiToShamsi(GETDATE())"); today = cur.fetchone()[0]
    cur.execute("""
    INSERT INTO dbo.name_mo
      (Code, Gcod, fname, Name, Addres2, datestart, l_gey, tartavalod,
       Man_f, Mah_f, Man_n, Mah_n, etebar, etebar2, etebar3, datebedehe, mabbedehe, sumbed, sumbes,
       CodeEghtesadi, VisitorPercent, Mary_date, ClubMember, clubIntroducer, ClubScore,
       Is_salary, ServiceType_salary, TypeBime_salary, IsMarried_salary, Code_personley_salary,
       isEnd_salary_work, number_children, telephons,
       Addres, Cherk, Zamin, memo1, pic, codeposti, Codemelli, Numbershenasname, Moaref, ShomareEghtesadi, Namepedar,
       AccountingNumber, Degree_salary, BankeName_salary, Field_salary, ShobeName_salary, ServiceTitle_salary,
       ServiceDate_salary, UnderWrite_salary, ThumbPrint_salary, ShoamreBime_salary, Jensiat_salary,
       shenaseMeli, shomareSabt, start_salary_work, end_salary_work)
    VALUES (?,?,?,?,?,?,1,'1300/01/01',
       0,N'بي حساب',0,N'بي حساب',0,0,0,?,0,0,0,
       0,0,'    /  /   ',0,0,0,
       0,0,0,0,0,0,0,?,
       '','','','','','','','','','','','','','','','','','','','','','','','','','')""", code, gcod, first_name, last_name, address, today, today, mobile_digits)
    cur.execute("INSERT INTO dbo.taf (cota, como, va, codgtaf, Sharh) VALUES (?,13,1,59,?)", code, (first_name + ' ' + last_name)[:100])
    # taf.Code is an IDENTITY column: read it back by the natural key (cota+codgtaf), not @@IDENTITY (not granted/needed)
    cur.execute("SELECT MAX(Code) FROM dbo.taf WHERE Cota=? AND codgtaf=59", code); taf = cur.fetchone()[0]
    cur.execute("UPDATE dbo.name_mo SET codetaf=? WHERE Code=?", taf, code)
    cur.execute("INSERT INTO dbo.DetailTBL (IDMaster, TabaghehBandiID, Comment, Va, darfn) VALUES (?,3,?,0,1)", code, mobile_digits)
    return code, taf

def create_order(cur, person_code, lines, sharhlp, tavasot='', usercode=0, anbar=1, status=0):
    """lines = [(kala_code, qty, unit_price)]. Returns (codlp, datelp, mablp)."""
    cur.execute(W_LOCK, 'shop:KalaOrder'); assert cur.fetchone()[0] >= 0
    cur.execute("SELECT ISNULL(MAX(Codlp),0)+1 FROM dbo.KalaOrder"); codlp = cur.fetchone()[0]
    cur.execute("SELECT dbo.MiladiToShamsi(GETDATE())"); datelp = cur.fetchone()[0]
    mablp = sum(q * p for _, q, p in lines)
    for num, (k, q, p) in enumerate(lines, 1):
        cur.execute("INSERT INTO dbo.KalaOrderDetail (Num, Codlp_, Codekala, Meg, Gey, sharh, AnbarCode) VALUES (?,?,?,?,?,?,?)",
                    num, codlp, k, q, p, '', anbar)
    cur.execute("""INSERT INTO dbo.KalaOrder (Usercode, Codlp, Codnlp, Datelp, tavasot, Sharhlp, takhfif, Mablp, Codf, va, Status, Naghd, Ischeck, keraye, avarez)
                   VALUES (?,?,?,?,?,?,0,?,-100,0,?,0,0,0,0)""", usercode, codlp, person_code, datelp, tavasot, sharhlp, mablp, status)
    return codlp, datelp, mablp
