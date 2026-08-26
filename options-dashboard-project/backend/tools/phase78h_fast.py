"""Phase 7.8H — Fast Volatility Research (optimized queries)."""

from __future__ import annotations
import math, os, sys, time
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_backend_dir)
sys.path.insert(0, _backend_dir)
import sqlite3

def _mean(v): return sum(v)/len(v) if v else 0.0
def _median(v):
    if not v: return 0.0
    s=sorted(v); n=len(s)
    return (s[n//2-1]+s[n//2])/2 if n%2==0 else s[n//2]
def _std(v):
    if len(v)<2: return 0.0
    m=_mean(v); return math.sqrt(sum((x-m)**2 for x in v)/(len(v)-1))
def _sem(v): return _std(v)/math.sqrt(len(v)) if len(v)>1 else 0.0
def _tstat(v):
    if len(v)<2: return 0.0
    return _mean(v)/_sem(v)
def _pval(t, df):
    if df<1: return 1.0
    x=abs(t)
    if df>30:
        p=math.exp(-0.5*x*x)/(x*math.sqrt(2*math.pi)) if x>0 else 0.5
        return min(2*p,1.0)
    if x>4: return 0.001
    if x>3: return 0.005
    if x>2.5: return 0.02
    if x>2.0: return 0.05
    if x>1.5: return 0.15
    return 0.3
def _corr(xs, ys):
    if len(xs)<3: return 0.0
    mx, my = _mean(xs), _mean(ys)
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    return num/(dx*dy) if dx*dy>0 else 0.0
def _percentile(vals, pct):
    s=sorted(vals)
    idx=int(pct/100*(len(s)-1))
    return s[max(0,min(idx,len(s)-1))]


def main():
    print("Phase 7.8H — Fast Volatility Research")
    print("=" * 70)

    db_path = os.path.join(_backend_dir, "paper_journal.db")
    conn = sqlite3.connect(db_path, timeout=120)

    try:
        # ==================================================================
        # Load GEX data
        # ==================================================================
        print("Loading GEX data...")
        t0 = time.time()
        ts_gex = conn.execute("""
            SELECT open_time, spot,
                   SUM(ABS(signed_gex)) as abs_gex,
                   SUM(signed_gex) as net_gex
            FROM historical_gex
            WHERE status='SUCCESS' AND calc_version='h_gex_v1'
            GROUP BY open_time ORDER BY open_time
        """).fetchall()

        timestamps = [r[0] for r in ts_gex]
        spots = [r[1] for r in ts_gex]
        abs_gex = [r[2] for r in ts_gex]
        net_gex = [r[3] for r in ts_gex]
        print(f"  GEX: {len(timestamps)} timestamps in {time.time()-t0:.1f}s")

        # Load NIFTY candles (high/low/close)
        print("Loading NIFTY candles...")
        nifty = conn.execute("""
            SELECT open_time, high, low, close FROM nifty_candles
            WHERE interval='3min' ORDER BY open_time
        """).fetchall()
        nifty_data = {r[0]: {"high": r[1], "low": r[2], "close": r[3]} for r in nifty}
        nifty_ts_list = [r[0] for r in nifty]
        print(f"  NIFTY: {len(nifty)} candles")

        def find_nifty_idx(ts):
            for i, nts in enumerate(nifty_ts_list):
                if nts > ts: return i
            return None

        def fwd_range(ts_idx, n_candles):
            ts = timestamps[ts_idx]
            spot = spots[ts_idx]
            nidx = find_nifty_idx(ts)
            if nidx is None or nidx + n_candles > len(nifty_ts_list): return None
            fc = [nifty_data[nifty_ts_list[nidx+j]] for j in range(n_candles)]
            hi = max(c["high"] for c in fc)
            lo = min(c["low"] for c in fc)
            rng = (hi - lo) / spot * 100 if spot > 0 else None
            abs_ret = abs(fc[-1]["close"] - spot) / spot * 100 if spot > 0 else None
            return {"range": rng, "abs_ret": abs_ret}

        # Compute forward ranges
        horizons = {"3m": 1, "6m": 2, "9m": 3, "15m": 5, "30m": 10, "60m": 20}
        print("Computing forward ranges...")
        fr = []
        for i in range(len(timestamps)):
            row = {}
            for label, nc in horizons.items():
                r = fwd_range(i, nc)
                if r: row[label] = r
            fr.append(row)

        # ==================================================================
        # GEX → Future Range (all horizons)
        # ==================================================================
        print("\n" + "=" * 70)
        print("GEX → FUTURE RANGE ANALYSIS")
        print("=" * 70)

        # GEX percentiles (only non-zero timestamps)
        nonzero_gex = [g for g in abs_gex if g > 0]
        print(f"Timestamps with non-zero GEX: {len(nonzero_gex)} / {len(abs_gex)} ({len(nonzero_gex)/len(abs_gex)*100:.1f}%)")
        if nonzero_gex:
            q20 = _percentile(nonzero_gex, 20)
            q40 = _percentile(nonzero_gex, 40)
            q60 = _percentile(nonzero_gex, 60)
            q80 = _percentile(nonzero_gex, 80)
            print(f"GEX percentiles (non-zero): p20={q20:,.0f}, p40={q40:,.0f}, p60={q60:,.0f}, p80={q80:,.0f}")
        else:
            q20 = q40 = q60 = q80 = 0
            print("WARNING: All GEX values are zero!")

        # Quintile analysis
        print("\n--- GEX Quintiles vs Future Range ---")
        for label in ["15m", "30m", "60m"]:
            print(f"\n  {label} Range:")
            for lo, hi, qname in [
                (0, q20, "Q1 (Very Low GEX)"),
                (q20, q40, "Q2 (Low GEX)"),
                (q40, q60, "Q3 (Medium GEX)"),
                (q60, q80, "Q4 (High GEX)"),
                (q80, float("inf"), "Q5 (Very High GEX)"),
            ]:
                ranges = [fr[i][label]["range"] for i in range(len(timestamps))
                          if lo <= abs_gex[i] < hi and label in fr[i]]
                if ranges:
                    print(f"    {qname}: N={len(ranges):>5}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%, std={_std(ranges):.4f}%")

        # Correlations
        print("\n--- Correlation: Abs GEX vs Future Range ---")
        for label in ["3m", "6m", "9m", "15m", "30m", "60m"]:
            xs = [abs_gex[i] for i in range(len(timestamps)) if label in fr[i]]
            ys = [fr[i][label]["range"] for i in range(len(timestamps)) if label in fr[i]]
            if len(xs) >= 10:
                c = _corr(xs, ys)
                print(f"  {label}: r={c:.4f}, R2={c*c:.4f}, N={len(xs)}")

        # Linear regression
        print("\n--- Linear Regression: 15m Range ~ Abs GEX ---")
        xs = [abs_gex[i] for i in range(len(timestamps)) if "15m" in fr[i]]
        ys = [fr[i]["15m"]["range"] for i in range(len(timestamps)) if "15m" in fr[i]]
        if len(xs) >= 10:
            mx, my = _mean(xs), _mean(ys)
            sx = [x-mx for x in xs]
            sy = [y-my for y in ys]
            b = sum(x*y for x,y in zip(sx,sy)) / sum(x**2 for x in sx)
            a = my - b * mx
            pred = [a + b*x for x in xs]
            ss_res = sum((y-p)**2 for y,p in zip(ys,pred))
            ss_tot = sum((y-my)**2 for y in ys)
            r2 = 1 - ss_res/ss_tot if ss_tot > 0 else 0
            print(f"  beta = {b:.10f} (each 1B GEX -> {b*1e9:.4f}% range change)")
            print(f"  alpha = {a:.4f}%")
            print(f"  R2 = {r2:.6f}")

        # Walk-forward R2
        print("\n--- Walk-Forward R2 (60/20/20) ---")
        n = len(xs)
        te = int(n*0.6); ve = int(n*0.8)
        for name, s, e in [("Train",0,te),("Val",te,ve),("Test",ve,n)]:
            sx, sy = xs[s:e], ys[s:e]
            if len(sx) < 10: continue
            mx_s, my_s = _mean(sx), _mean(sy)
            scx = [x-mx_s for x in sx]; scy = [y-my_s for y in sy]
            b = sum(x*y for x,y in zip(scx,scy)) / sum(x**2 for x in scx)
            a = my_s - b * mx_s
            pred = [a+b*x for x in sx]
            ss_r = sum((y-p)**2 for y,p in zip(sy,pred))
            ss_t = sum((y-my_s)**2 for y in sy)
            r2 = 1 - ss_r/ss_t if ss_t > 0 else 0
            print(f"  {name}: N={len(sx)}, R2={r2:.6f}")

        # ==================================================================
        # Regime Analysis
        # ==================================================================
        print("\n" + "=" * 70)
        print("REGIME ANALYSIS")
        print("=" * 70)

        for label in ["15m", "30m", "60m"]:
            print(f"\n  {label} Range by Regime:")
            for regime, cond in [("NEG_GAMMA", lambda i: net_gex[i] < 0),
                                  ("POS_GAMMA", lambda i: net_gex[i] > 0),
                                  ("NEUTRAL", lambda i: net_gex[i] == 0)]:
                ranges = [fr[i][label]["range"] for i in range(len(timestamps))
                          if cond(i) and label in fr[i]]
                if ranges:
                    print(f"    {regime}: N={len(ranges)}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%")

        # NEG_GAMMA walk-forward
        print("\n--- NEG_GAMMA Walk-Forward (15m Range) ---")
        ng_idx = [i for i in range(len(timestamps)) if net_gex[i] < 0]
        n_ng = len(ng_idx)
        te = int(n_ng*0.6); ve = int(n_ng*0.8)
        for name, s, e in [("Train",0,te),("Val",te,ve),("Test",ve,n_ng)]:
            idx = ng_idx[s:e]
            ranges = [fr[i]["15m"]["range"] for i in idx if "15m" in fr[i]]
            if ranges:
                print(f"  {name}: N={len(ranges)}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%")

        # ==================================================================
        # Option-Level: Straddle Analysis
        # ==================================================================
        print("\n" + "=" * 70)
        print("OPTION-LEVEL: STRADDLE ANALYSIS")
        print("=" * 70)

        # Load CE/PE pairs at ATM strike
        print("Loading ATM straddle data...")
        straddle = conn.execute("""
            SELECT c1.open_time,
                   s1.strike_price,
                   c1.close as ce_price,
                   c2.close as pe_price,
                   s1.lot_size,
                   s1.expiry
            FROM option_candles c1
            JOIN contract_specs s1 ON c1.instrument_key = s1.instrument_key
            JOIN option_candles c2 ON c1.open_time = c2.open_time
            JOIN contract_specs s2 ON c2.instrument_key = s2.instrument_key
            WHERE s1.instrument_type = 'CE' AND s2.instrument_type = 'PE'
              AND s1.strike_price = s2.strike_price
              AND s1.expiry = s2.expiry
              AND c1.close > 0 AND c2.close > 0
        """).fetchall()
        print(f"  CE/PE pairs loaded: {len(straddle):,}")

        # Find ATM straddles (closest strike to spot)
        ts_straddle = defaultdict(list)
        for r in straddle:
            ts_straddle[r[0]].append({
                "strike": r[1], "ce": r[2], "pe": r[3],
                "lot_size": r[4], "expiry": r[5],
                "straddle": r[2] + r[3],
            })

        atm_straddles = []
        for i, ts in enumerate(timestamps):
            if ts not in ts_straddle: continue
            spot = spots[i]
            pairs = ts_straddle[ts]
            # Find closest to spot
            closest = min(pairs, key=lambda p: abs(p["strike"] - spot))
            if abs(closest["strike"] - spot) / spot * 100 < 1.0:  # Within 1% of spot
                atm_straddles.append({
                    "timestamp": ts, "spot": spot, "idx": i,
                    "strike": closest["strike"],
                    "straddle": closest["straddle"],
                    "ce": closest["ce"], "pe": closest["pe"],
                    "abs_gex": abs_gex[i], "net_gex": net_gex[i],
                    "range_15m": fr[i].get("15m", {}).get("range"),
                    "range_30m": fr[i].get("30m", {}).get("range"),
                    "range_60m": fr[i].get("60m", {}).get("range"),
                })

        print(f"  ATM straddles: {len(atm_straddles)}")

        if atm_straddles:
            gex_vals = [d["abs_gex"] for d in atm_straddles]
            q20_s = _percentile(gex_vals, 20)
            q80_s = _percentile(gex_vals, 80)

            print("\n--- Straddle by GEX Quintile ---")
            for lo, hi, qname in [
                (0, q20_s, "Q1 (Very Low)"),
                (q20_s, q80_s, "Q2-Q4 (Medium)"),
                (q80_s, float("inf"), "Q5 (Very High)"),
            ]:
                group = [d for d in atm_straddles if lo <= d["abs_gex"] < hi]
                if group:
                    prem = [d["straddle"] for d in group]
                    r15 = [d["range_15m"] for d in group if d["range_15m"]]
                    r30 = [d["range_30m"] for d in group if d["range_30m"]]
                    r60 = [d["range_60m"] for d in group if d["range_60m"]]
                    print(f"  {qname}: N={len(group)}")
                    print(f"    Avg straddle premium: {_mean(prem):.2f} pts")
                    if r15: print(f"    Avg 15m range: {_mean(r15):.4f}%")
                    if r30: print(f"    Avg 30m range: {_mean(r30):.4f}%")
                    if r60: print(f"    Avg 60m range: {_mean(r60):.4f}%")

            # Transaction cost analysis
            print("\n--- Transaction Cost Analysis ---")
            high_gex = [d for d in atm_straddles if d["abs_gex"] > q80_s]
            if high_gex:
                avg_prem = _mean([d["straddle"] for d in high_gex])
                avg_range_15 = _mean([d["range_15m"] for d in high_gex if d["range_15m"]])
                avg_spot = _mean([d["spot"] for d in high_gex])
                range_pts = avg_range_15 / 100 * avg_spot
                cost_pts = avg_prem * 0.0015  # 0.15% round-trip

                print(f"  High GEX short straddle:")
                print(f"    Avg premium: {avg_prem:.2f} pts")
                print(f"    Avg 15m range: {avg_range_15:.4f}% = {range_pts:.2f} pts")
                print(f"    Gross P&L (if range < premium): {avg_prem - range_pts:.2f} pts")
                print(f"    Estimated costs: {cost_pts:.2f} pts")
                print(f"    Net P&L: {avg_prem - range_pts - cost_pts:.2f} pts")

            # Walk-forward
            print("\n--- Walk-Forward Straddle (High GEX) ---")
            n_s = len(atm_straddles)
            te = int(n_s*0.6); ve = int(n_s*0.8)
            for name, s, e in [("Train",0,te),("Val",te,ve),("Test",ve,n_s)]:
                split = atm_straddles[s:e]
                gex_split = [d["abs_gex"] for d in split]
                if not gex_split: continue
                q80_split = _percentile(gex_split, 80)
                high = [d for d in split if d["abs_gex"] > q80_split]
                if high:
                    prem = _mean([d["straddle"] for d in high])
                    r15 = [d["range_15m"] for d in high if d["range_15m"]]
                    if r15:
                        rng = _mean(r15)
                        spot_avg = _mean([d["spot"] for d in high])
                        range_pts = rng / 100 * spot_avg
                        print(f"  {name}: N={len(high)}, premium={prem:.2f}, range_15m={rng:.4f}%, gross={prem-range_pts:.2f} pts")

        # ==================================================================
        # NEG_GAMMA Investigation
        # ==================================================================
        print("\n" + "=" * 70)
        print("NEG_GAMMA INVESTIGATION")
        print("=" * 70)

        neg_idx = [i for i in range(len(timestamps)) if net_gex[i] < 0]
        pos_idx = [i for i in range(len(timestamps)) if net_gex[i] > 0]
        print(f"NEG_GAMMA: {len(neg_idx)} ({len(neg_idx)/len(timestamps)*100:.1f}%)")
        print(f"POS_GAMMA: {len(pos_idx)} ({len(pos_idx)/len(timestamps)*100:.1f}%)")

        # Forward abs return by regime
        for label in ["15m", "30m", "60m"]:
            print(f"\n  {label} Abs Return by Regime:")
            for name, idx in [("NEG_GAMMA", neg_idx), ("POS_GAMMA", pos_idx)]:
                rets = [fr[i][label]["abs_ret"] for i in idx if label in fr[i] and fr[i][label]["abs_ret"] is not None]
                if rets:
                    print(f"    {name}: N={len(rets)}, mean={_mean(rets):.4f}%, median={_median(rets):.4f}%")

        # ==================================================================
        # High-GEX Range Compression Verification
        # ==================================================================
        print("\n" + "=" * 70)
        print("HIGH-GEX RANGE COMPRESSION VERIFICATION")
        print("=" * 70)

        for label in ["3m", "6m", "9m", "15m", "30m", "60m"]:
            all_r = [(abs_gex[i], fr[i][label]["range"]) for i in range(len(timestamps))
                     if label in fr[i]]
            if not all_r: continue
            gex_v = [g for g,_ in all_r]
            q20_l = _percentile(gex_v, 20)
            q80_l = _percentile(gex_v, 80)
            low = [r for g,r in all_r if g < q20_l]
            high = [r for g,r in all_r if g > q80_l]
            if low and high:
                diff = _mean(low) - _mean(high)
                t = _tstat(low + high)
                p = _pval(t, len(low)+len(high)-2)
                print(f"  {label}: low_GEX={_mean(low):.4f}%, high_GEX={_mean(high):.4f}%, diff={diff:.4f}%, t={t:.3f}, p={p:.4f}")

        # Rolling windows
        print("\n--- Rolling Window Stability (15m Range Compression) ---")
        all_15 = [(abs_gex[i], fr[i]["15m"]["range"], timestamps[i])
                  for i in range(len(timestamps)) if "15m" in fr[i]]
        all_15.sort(key=lambda x: x[2])
        if all_15:
            from datetime import datetime as dt, timedelta
            def to_dt(v):
                if isinstance(v, str): return dt.fromisoformat(v.replace("Z","").split(".")[0])
                return v
            min_t = to_dt(all_15[0][2]); max_t = to_dt(all_15[-1][2])
            current = min_t; wnum = 0
            while current + timedelta(days=90) <= max_t:
                wend = current + timedelta(days=90)
                w = [(g,r) for g,r,t in all_15 if to_dt(t) >= current and to_dt(t) < wend]
                if len(w) >= 20:
                    wnum += 1
                    gv = [g for g,_ in w]
                    q20_w = _percentile(gv, 20); q80_w = _percentile(gv, 80)
                    lo_w = [r for g,r in w if g < q20_w]
                    hi_w = [r for g,r in w if g > q80_w]
                    if lo_w and hi_w:
                        print(f"    W{wnum} ({current.strftime('%Y-%m-%d')}): N={len(w)}, diff={_mean(lo_w)-_mean(hi_w):.4f}%, low={_mean(lo_w):.4f}%, high={_mean(hi_w):.4f}%")
                current += timedelta(days=30)

        # ==================================================================
        # IV Analysis (if data available)
        # ==================================================================
        print("\n" + "=" * 70)
        print("IV ANALYSIS")
        print("=" * 70)

        iv_count = conn.execute("""
            SELECT COUNT(DISTINCT open_time) FROM option_greeks
            WHERE implied_volatility IS NOT NULL AND implied_volatility > 0
                  AND implied_volatility < 5.0 AND calc_version='greeks_v3'
        """).fetchone()[0]
        print(f"  Timestamps with valid IV: {iv_count}")

        if iv_count > 100:
            iv_data = conn.execute("""
                SELECT open_time, AVG(implied_volatility) as avg_iv
                FROM option_greeks
                WHERE implied_volatility IS NOT NULL AND implied_volatility > 0
                      AND implied_volatility < 5.0 AND calc_version='greeks_v3'
                GROUP BY open_time
            """).fetchall()
            iv_map = {r[0]: r[1] for r in iv_data}

            # IV vs realized vol
            iv_rv = [(iv_map.get(timestamps[i], 0), fr[i].get("15m", {}).get("range"))
                     for i in range(len(timestamps))
                     if timestamps[i] in iv_map and fr[i].get("15m", {}).get("range") is not None]

            if iv_rv:
                ivs = [x for x,_ in iv_rv]
                rvs = [y for _,y in iv_rv]
                c = _corr(ivs, rvs)
                print(f"  IV vs RV (15m): N={len(iv_rv)}, r={c:.4f}, mean_IV={_mean(ivs):.4f}, mean_RV={_mean(rvs):.4f}%")

        # ==================================================================
        # Database Safety
        # ==================================================================
        print("\n" + "=" * 70)
        print("DATABASE SAFETY")
        print("=" * 70)
        for t in ['option_candles','option_greeks','historical_gex','nifty_candles','contract_specs']:
            r = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()
            print(f"  {t}: {r[0]}")
        r = conn.execute('PRAGMA integrity_check').fetchone()
        print(f"  Integrity: {r[0]}")

    finally:
        conn.close()

    print("\nRESEARCH COMPLETE")


if __name__ == "__main__":
    main()
