READS = {}
READS['R1_groups'] = """
SELECT g.Code, g.Name, g.g_kala AS ParentCode,
       (SELECT COUNT(*) FROM dbo.Kala k WHERE k.Gcod = g.Code AND k.active = 1) AS ActiveProducts
FROM dbo.Gkala g
WHERE g.Code > 0
ORDER BY g.g_kala, g.Code
"""
READS['R2_products'] = """
SELECT k.Code, k.Name, k.Gcod AS GroupCode, k.v1 AS UnitCode, k.pic AS Pic,
       k.Gey AS Price1, k.Geycf AS Price2, k.gey3 AS Price3, k.gey4 AS Price4, k.gey5 AS Price5,
       ISNULL(s.Stock, 0) AS Stock,
       ISNULL(o.OpenOrderQty, 0) AS OpenOrderQty
FROM dbo.Kala k
LEFT JOIN (SELECT Codekala, SUM(ISNULL(Megv,0)) - SUM(ISNULL(Megs,0)) AS Stock
           FROM dbo.kardex_an
           GROUP BY Codekala) s ON s.Codekala = k.Code
LEFT JOIN (SELECT d.Codekala,
                  SUM(CASE WHEN d.Meg - ISNULL(f.Meg,0) > 0 THEN d.Meg - ISNULL(f.Meg,0) ELSE 0 END) AS OpenOrderQty
           FROM dbo.KalaOrderDetail d
           JOIN dbo.KalaOrder h ON h.Codlp = d.Codlp_ AND ISNULL(h.va,0) = 0
           LEFT JOIN (SELECT ordercode, orderdetailcode, Codekala, SUM(Meg) AS Meg
                      FROM dbo.facto WHERE ISNULL(ordercode,0) > 0
                      GROUP BY ordercode, orderdetailcode, Codekala) f
                  ON f.ordercode = d.Codlp_ AND f.orderdetailcode = d.Num AND f.Codekala = d.Codekala
           GROUP BY d.Codekala) o ON o.Codekala = k.Code
WHERE k.active = 1 AND k.Code > 0
ORDER BY k.Code
"""
READS['R3_stock_one'] = """
SELECT Codekala, Codanbar, SUM(ISNULL(Megv,0)) - SUM(ISNULL(Megs,0)) AS Stock
FROM dbo.kardex_an WHERE Codekala = ? GROUP BY Codekala, Codanbar
"""
READS['R4_person_by_mobile'] = """
SELECT TOP 1 n.Code
FROM dbo.DetailTBL d
JOIN dbo.name_mo n ON n.Code = d.IDMaster
WHERE d.Va = 0 AND d.TabaghehBandiID IN (1, 3)
  AND LEN(RTRIM(d.Comment)) BETWEEN 10 AND 14
  AND RIGHT(RTRIM(d.Comment), 10) = ?
ORDER BY n.Code
"""
READS['R5_orders'] = """
SELECT h.Codlp, h.Codnlp, h.Datelp, h.Mablp, h.takhfif, h.avarez, h.Status, h.Codf, h.va, h.Sharhlp, h.tavasot,
       (SELECT SUM(d.Meg) FROM dbo.KalaOrderDetail d WHERE d.Codlp_ = h.Codlp) AS OrderedQty,
       (SELECT SUM(f.Meg) FROM dbo.facto f WHERE f.ordercode = h.Codlp) AS InvoicedQty
FROM dbo.KalaOrder h
WHERE h.Codnlp = ? ORDER BY h.Codlp DESC
"""
READS['R6_order_lines'] = """
SELECT d.Num, d.Codekala, k.Name, d.Meg, d.Gey, d.Meg * d.Gey AS LineAmount,
       (SELECT SUM(f.Meg) FROM dbo.facto f
         WHERE f.ordercode = d.Codlp_ AND f.orderdetailcode = d.Num AND f.Codekala = d.Codekala) AS InvoicedQty
FROM dbo.KalaOrderDetail d LEFT JOIN dbo.Kala k ON k.Code = d.Codekala
WHERE d.Codlp_ = ? ORDER BY d.Num
"""
