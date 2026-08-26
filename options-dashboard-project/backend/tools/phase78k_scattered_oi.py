#!/usr/bin/env python3
"""Phase 7.8K — Scattered Zero-OI Forensic Audit (read-only)."""

import sqlite3
import sys
from collections import Counter

DB = "paper_journal.db"

def run():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    c = db.cursor()

    # ── 1. Basic counts (non-2025-10-07) ──────────────────────────
    print("=" * 70)
    print("SECTION 1: NON-2025-10-07 ZERO-OI ROWS")
    print("=" * 70)

    c.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi,
               SUM(CASE WHEN oc.open_interest > 0 THEN 1 ELSE 0 END) as pos_oi
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
    """)
    r = c.fetchone()
    total_other = r["total"]
    zero_other = r["zero_oi"]
    pos_other = r["pos_oi"]
    print(f"  Total rows (excl 2025-10-07): {total_other}")
    print(f"  Zero-OI rows:                 {zero_other}")
    print(f"  Positive-OI rows:             {pos_other}")
    print(f"  Zero-OI %:                    {zero_other/total_other*100:.3f}%")

    # ── 2. Breakdown by expiry ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 2: ZERO-OI BY EXPIRY (top 20)")
    print("=" * 70)

    c.execute("""
        SELECT cs.expiry,
               COUNT(*) as total,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi,
               SUM(CASE WHEN oc.open_interest > 0 THEN 1 ELSE 0 END) as pos_oi,
               ROUND(100.0 * SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) as pct
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
        GROUP BY cs.expiry
        HAVING zero_oi > 0
        ORDER BY zero_oi DESC
        LIMIT 20
    """)
    for r in c.fetchall():
        print(f"  expiry={r['expiry']}, total={r['total']}, zero_OI={r['zero_oi']}, pct={r['pct']}%")

    # ── 3. Breakdown by date (trading day of the candle, not expiry) ──
    print("\n" + "=" * 70)
    print("SECTION 3: ZERO-OI BY CANDLE DATE (not expiry)")
    print("=" * 70)

    c.execute("""
        SELECT SUBSTR(oc.open_time, 1, 10) as candle_date,
               COUNT(*) as total,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi,
               ROUND(100.0 * SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) as pct
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY candle_date
        ORDER BY zero_oi DESC
        LIMIT 20
    """)
    for r in c.fetchall():
        print(f"  date={r['candle_date']}, zero_OI={r['zero_oi']}, total_that_date={r['total']}, pct={r['pct']}%")

    # ── 4. Breakdown by candle time-of-day ────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 4: ZERO-OI BY TIME OF DAY (HH:MM)")
    print("=" * 70)

    c.execute("""
        SELECT SUBSTR(oc.open_time, 12, 5) as tod,
               COUNT(*) as cnt
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY tod
        ORDER BY cnt DESC
        LIMIT 15
    """)
    for r in c.fetchall():
        print(f"  time={r['tod']}, zero_OI_count={r['cnt']}")

    # ── 5. Unique instruments with zero-OI ────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 5: UNIQUE INSTRUMENTS WITH ZERO-OI (non-2025-10-07)")
    print("=" * 70)

    c.execute("""
        SELECT oc.instrument_key, cs.expiry, cs.strike_price, cs.instrument_type,
               COUNT(*) as total_candles,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi,
               SUM(CASE WHEN oc.open_interest > 0 THEN 1 ELSE 0 END) as pos_oi,
               ROUND(100.0 * SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY oc.instrument_key
        ORDER BY zero_oi DESC
        LIMIT 30
    """)
    for r in c.fetchall():
        print(f"  {r['instrument_key']} | expiry={r['expiry']} | strike={r['strike_price']} | {r['instrument_type']} | candles={r['total_candles']} | zero={r['zero_oi']} | pos={r['pos_oi']} | pct={r['pct']}%")

    c.execute("""
        SELECT COUNT(DISTINCT oc.instrument_key) as cnt
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
    """)
    print(f"\n  Total unique instruments with any zero-OI: {c.fetchone()['cnt']}")

    # ── 6. Instrument type breakdown ──────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 6: ZERO-OI BY INSTRUMENT TYPE (CE/PE)")
    print("=" * 70)

    c.execute("""
        SELECT cs.instrument_type,
               COUNT(*) as total,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
        GROUP BY cs.instrument_type
    """)
    for r in c.fetchall():
        print(f"  {r['instrument_type']}: total={r['total']}, zero_OI={r['zero_oi']}")

    # ── 7. Strike distance from ATM ───────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 7: ZERO-OI BY STRIKE DISTANCE FROM ATM")
    print("=" * 70)

    c.execute("""
        WITH atm AS (
            SELECT oc.instrument_key, oc.open_time,
                   cs.strike_price, cs.expiry,
                   MIN(ABS(cs2.strike_price - cs.strike_price)) as atm_dist
            FROM option_candles oc
            JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
            JOIN contract_specs cs2 ON cs2.expiry = cs.expiry
                                  AND cs2.instrument_type = cs.instrument_type
            WHERE cs.expiry != '2025-10-07'
              AND oc.open_interest = 0
            GROUP BY oc.instrument_key, oc.open_time
        )
        SELECT
            CASE
                WHEN atm_dist = 0 THEN 'ATM'
                WHEN atm_dist <= 50 THEN 'Near (<=50)'
                WHEN atm_dist <= 100 THEN 'Mid (51-100)'
                WHEN atm_dist <= 200 THEN 'Far (101-200)'
                ELSE 'Very Far (>200)'
            END as bucket,
            COUNT(*) as cnt
        FROM atm
        GROUP BY bucket
        ORDER BY cnt DESC
    """)
    # This query is complex, let me simplify
    c.execute("""
        SELECT cs.strike_price,
               COUNT(*) as zero_oi_count
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY cs.strike_price
        ORDER BY zero_oi_count DESC
        LIMIT 15
    """)
    for r in c.fetchall():
        print(f"  strike={r['strike_price']}, zero_OI_count={r['zero_oi_count']}")

    # ── 8. Sample zero-OI rows vs same instrument nearby dates ────
    print("\n" + "=" * 70)
    print("SECTION 8: SAMPLE ZERO-OI ROWS — CROSS-DATE COMPARISON")
    print("=" * 70)

    c.execute("""
        SELECT oc.instrument_key, oc.open_time, oc.open_interest, oc.close, oc.volume,
               cs.strike_price, cs.instrument_type, cs.expiry
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        ORDER BY oc.open_time
        LIMIT 10
    """)
    zero_rows = c.fetchall()
    for r in zero_rows:
        print(f"  ZERO: {r['instrument_key']} | {r['open_time']} | OI=0 | close={r['close']} | vol={r['volume']} | {r['instrument_type']} strike={r['strike_price']}")

    # For each, check same instrument on adjacent dates
    if zero_rows:
        ik = zero_rows[0]["instrument_key"]
        print(f"\n  Cross-date check for {ik}:")
        c.execute("""
            SELECT SUBSTR(open_time, 1, 10) as d, open_interest, close, volume
            FROM option_candles
            WHERE instrument_key = ?
            ORDER BY open_time
        """, (ik,))
        for r in c.fetchall():
            marker = " *** ZERO ***" if r["open_interest"] == 0 else ""
            print(f"    {r['d']}: OI={r['open_interest']}, close={r['close']}, vol={r['volume']}{marker}")

    # ── 9. Candle source column ───────────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 9: ZERO-OI BY SOURCE")
    print("=" * 70)

    c.execute("""
        SELECT oc.source,
               COUNT(*) as total,
               SUM(CASE WHEN oc.open_interest = 0 THEN 1 ELSE 0 END) as zero_oi
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
        GROUP BY oc.source
    """)
    for r in c.fetchall():
        print(f"  source={r['source']}, total={r['total']}, zero_OI={r['zero_oi']}")

    # ── 10. GEX impact ────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 10: GEX IMPACT")
    print("=" * 70)

    c.execute("""
        SELECT hg.status, COUNT(*) as cnt
        FROM historical_gex hg
        JOIN contract_specs cs ON hg.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
        GROUP BY hg.status
    """)
    for r in c.fetchall():
        print(f"  {r['status']}: {r['cnt']}")

    # How many of the EXCLUDED rows correspond to zero-OI candles?
    c.execute("""
        SELECT COUNT(*) as cnt
        FROM historical_gex hg
        JOIN option_candles oc ON hg.instrument_key = oc.instrument_key AND hg.open_time = oc.open_time
        JOIN contract_specs cs ON hg.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
          AND hg.status = 'EXCLUDED'
    """)
    print(f"  EXCLUDED GEX rows matching zero-OI candles (non-2025-10-07): {c.fetchone()['cnt']}")

    # Any SUCCESS GEX rows with zero-OI candles?
    c.execute("""
        SELECT COUNT(*) as cnt
        FROM historical_gex hg
        JOIN option_candles oc ON hg.instrument_key = oc.instrument_key AND hg.open_time = oc.open_time
        JOIN contract_specs cs ON hg.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
          AND hg.status = 'SUCCESS'
    """)
    print(f"  SUCCESS GEX rows matching zero-OI candles (non-2025-10-07): {c.fetchone()['cnt']}")

    # ── 11. Are zero-OI rows always last candles of the day? ──────
    print("\n" + "=" * 70)
    print("SECTION 11: ARE ZERO-OI ROWS CONCENTRATED AT END OF SESSION?")
    print("=" * 70)

    c.execute("""
        SELECT SUBSTR(oc.open_time, 12, 5) as tod,
               COUNT(*) as cnt,
               COUNT(DISTINCT SUBSTR(oc.open_time, 1, 10)) as dates
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY tod
        ORDER BY tod
    """)
    for r in c.fetchall():
        print(f"  {r['tod']}: {r['cnt']} zero-OI rows across {r['dates']} dates")

    # ── 12. Volume comparison: zero-OI vs positive-OI at same time ─
    print("\n" + "=" * 70)
    print("SECTION 12: VOLUME COMPARISON")
    print("=" * 70)

    c.execute("""
        SELECT
            CASE WHEN oc.open_interest = 0 THEN 'zero_OI' ELSE 'positive_OI' END as cat,
            COUNT(*) as cnt,
            ROUND(AVG(oc.volume), 0) as avg_vol,
            ROUND(AVG(oc.close), 2) as avg_close,
            ROUND(MIN(oc.close), 2) as min_close,
            ROUND(MAX(oc.close), 2) as max_close
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
        GROUP BY cat
    """)
    for r in c.fetchall():
        print(f"  {r['cat']}: n={r['cnt']}, avg_vol={r['avg_vol']}, avg_close={r['avg_close']}, close_range=[{r['min_close']}, {r['max_close']}]")

    # ── 13. Expiry weekday analysis ───────────────────────────────
    print("\n" + "=" * 70)
    print("SECTION 13: EXPIRY DATE WEEKDAY ANALYSIS")
    print("=" * 70)

    c.execute("""
        SELECT cs.expiry,
               COUNT(*) as zero_oi,
               CASE CAST(strftime('%w', cs.expiry) AS INTEGER)
                   WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue'
                   WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri'
                   WHEN 6 THEN 'Sat'
               END as weekday
        FROM option_candles oc
        JOIN contract_specs cs ON oc.instrument_key = cs.instrument_key
        WHERE cs.expiry != '2025-10-07'
          AND oc.open_interest = 0
        GROUP BY cs.expiry
        ORDER BY zero_oi DESC
    """)
    for r in c.fetchall():
        print(f"  expiry={r['expiry']} ({r['weekday']}): {r['zero_oi']} zero-OI rows")

    db.close()
    print("\n" + "=" * 70)
    print("AUDIT COMPLETE — READ-ONLY, NO PRODUCTION CHANGES")
    print("=" * 70)


if __name__ == "__main__":
    run()
