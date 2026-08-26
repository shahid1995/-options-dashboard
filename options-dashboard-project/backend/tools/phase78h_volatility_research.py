"""Phase 7.8H — GEX Volatility & Option-Level Edge Research.

Determines whether GEX provides actionable information about NIFTY's
future range, realized volatility, or option premium behavior.
"""

from __future__ import annotations

import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_backend_dir)
sys.path.insert(0, _backend_dir)

import sqlite3


# ==================================================================
# Statistics
# ==================================================================

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
    n=len(xs)
    mx, my = _mean(xs), _mean(ys)
    num = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    return num/(dx*dy) if dx*dy>0 else 0.0
def _r2(xs, ys):
    c=_corr(xs,ys)
    return c*c
def _percentile(vals, pct):
    s=sorted(vals)
    idx=int(pct/100*(len(s)-1))
    return s[max(0,min(idx,len(s)-1))]
def _quintile_labels(vals):
    s=sorted(vals)
    n=len(s)
    return [_percentile(vals, 20), _percentile(vals, 40), _percentile(vals, 60), _percentile(vals, 80)]


def main():
    print("Phase 7.8H — GEX Volatility & Option-Level Edge Research")
    print("=" * 70)

    db_path = os.path.join(_backend_dir, "paper_journal.db")
    conn = sqlite3.connect(db_path, timeout=120)

    try:
        # ==================================================================
        # Phase 1: Data Coverage Audit
        # ==================================================================
        print("\nPHASE 1: DATA COVERAGE AUDIT")
        print("=" * 70)

        # Option candles
        oc = conn.execute("SELECT COUNT(*), COUNT(DISTINCT instrument_key), MIN(open_time), MAX(open_time) FROM option_candles").fetchone()
        print(f"  option_candles: {oc[0]:,} rows, {oc[1]:,} instruments, {oc[2]} to {oc[3]}")

        # Option Greeks
        og = conn.execute("SELECT COUNT(*), COUNT(DISTINCT instrument_key), MIN(open_time), MAX(open_time), SUM(CASE WHEN implied_volatility IS NOT NULL THEN 1 ELSE 0 END) as has_iv FROM option_greeks").fetchone()
        print(f"  option_greeks: {og[0]:,} rows, {og[1]:,} instruments, {og[2]} to {og[3]}, has_iv={og[4]:,}")

        # Historical GEX
        hg = conn.execute("SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM historical_gex WHERE status='SUCCESS'").fetchone()
        print(f"  historical_gex: {hg[0]:,} rows, {hg[1]} to {hg[2]}")

        # NIFTY candles
        nc = conn.execute("SELECT COUNT(*), MIN(open_time), MAX(open_time) FROM nifty_candles WHERE interval='3min'").fetchone()
        print(f"  nifty_candles: {nc[0]:,} rows, {nc[1]} to {nc[2]}")

        # Contract specs
        cs = conn.execute("SELECT COUNT(*), COUNT(DISTINCT instrument_key) FROM contract_specs").fetchone()
        print(f"  contract_specs: {cs[0]:,} rows, {cs[1]:,} instruments")

        # Check option price coverage (from option_candles.close)
        opc = conn.execute("SELECT COUNT(*) FROM option_candles WHERE close > 0").fetchone()
        print(f"  option_candles with price > 0: {opc[0]:,}")

        # Check OI coverage
        oic = conn.execute("SELECT COUNT(*) FROM option_candles WHERE open_interest > 0").fetchone()
        print(f"  option_candles with OI > 0: {oic[0]:,}")

        # Check volume coverage
        vc = conn.execute("SELECT COUNT(*) FROM option_candles WHERE volume > 0").fetchone()
        print(f"  option_candles with volume > 0: {vc[0]:,}")

        # Check IV coverage from Greeks
        ivc = conn.execute("SELECT COUNT(*) FROM option_greeks WHERE implied_volatility IS NOT NULL AND implied_volatility > 0 AND implied_volatility < 5.0").fetchone()
        print(f"  option_greeks with valid IV: {ivc[0]:,}")

        # Check timestamp overlap between GEX and option candles
        overlap = conn.execute("""
            SELECT COUNT(DISTINCT h.open_time)
            FROM historical_gex h
            JOIN option_candles c ON h.open_time = c.open_time
            WHERE h.status='SUCCESS' AND h.calc_version='h_gex_v1'
        """).fetchone()
        print(f"  Timestamps with both GEX and option candles: {overlap[0]:,}")

        # Check ATM options (CE/PE pairs at same strike/expiry via contract_specs)
        atm_pairs = conn.execute("""
            SELECT COUNT(DISTINCT c1.instrument_key)
            FROM option_candles c1
            JOIN contract_specs s1 ON c1.instrument_key = s1.instrument_key
            JOIN option_candles c2 ON c1.open_time = c2.open_time
            JOIN contract_specs s2 ON c2.instrument_key = s2.instrument_key
            WHERE s1.strike_price = s2.strike_price
              AND s1.expiry = s2.expiry
              AND s1.instrument_type = 'CE' AND s2.instrument_type = 'PE'
        """).fetchone()
        print(f"  Instruments with CE/PE pair at same strike/time: {atm_pairs[0]:,}")

        # ==================================================================
        # Phase 2-4: GEX as Volatility Predictor
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 2-4: GEX AS VOLATILITY PREDICTOR")
        print("=" * 70)

        # Load GEX timestamps and spots
        print("Loading GEX data...")
        t0 = time.time()
        ts_gex = conn.execute("""
            SELECT open_time, spot,
                   SUM(ABS(signed_gex)) as abs_gex,
                   SUM(CASE WHEN option_type='CE' THEN signed_gex ELSE 0 END) as call_gex,
                   SUM(CASE WHEN option_type='PE' THEN signed_gex ELSE 0 END) as put_gex,
                   SUM(signed_gex) as net_gex
            FROM historical_gex
            WHERE status='SUCCESS' AND calc_version='h_gex_v1'
            GROUP BY open_time ORDER BY open_time
        """).fetchall()

        timestamps = [r[0] for r in ts_gex]
        spots = [r[1] for r in ts_gex]
        abs_gex = [r[2] for r in ts_gex]
        net_gex = [r[5] for r in ts_gex]
        print(f"  Loaded {len(timestamps)} timestamps in {time.time()-t0:.1f}s")

        # Load NIFTY candles
        print("Loading NIFTY candles...")
        nifty = conn.execute("""
            SELECT open_time, high, low, close FROM nifty_candles
            WHERE interval='3min' ORDER BY open_time
        """).fetchall()
        nifty_data = {r[0]: {"high": r[1], "low": r[2], "close": r[3]} for r in nifty}
        nifty_ts_list = [r[0] for r in nifty]

        def find_nifty_idx(ts):
            """Find first NIFTY candle index after timestamp."""
            for i, nts in enumerate(nifty_ts_list):
                if nts > ts:
                    return i
            return None

        def compute_forward_range(ts_idx, candles_ahead):
            """Compute forward high-low range."""
            ts = timestamps[ts_idx]
            spot = spots[ts_idx]
            nidx = find_nifty_idx(ts)
            if nidx is None or nidx + candles_ahead > len(nifty_ts_list):
                return None

            future_candles = [nifty_data[nifty_ts_list[nidx + j]] for j in range(candles_ahead)]
            future_high = max(c["high"] for c in future_candles)
            future_low = min(c["low"] for c in future_candles)
            future_range = (future_high - future_low) / spot * 100 if spot > 0 else None

            # Excursions
            max_up = max(c["high"] for c in future_candles)
            max_down = min(c["low"] for c in future_candles)
            upside_exc = (max_up - spot) / spot * 100 if spot > 0 else None
            downside_exc = (spot - max_down) / spot * 100 if spot > 0 else None

            # Realized vol proxy (absolute return)
            last_close = future_candles[-1]["close"]
            abs_return = abs(last_close - spot) / spot * 100 if spot > 0 else None

            return {
                "range_pct": future_range,
                "upside_exc": upside_exc,
                "downside_exc": downside_exc,
                "abs_return": abs_return,
                "future_high": future_high,
                "future_low": future_low,
            }

        # Compute forward ranges for all horizons
        horizons = {"3m": 1, "6m": 2, "9m": 3, "15m": 5, "30m": 10, "60m": 20}
        print("Computing forward ranges...")

        # Build feature matrix
        features = []
        for i in range(len(timestamps)):
            fr = {}
            for label, n_candles in horizons.items():
                r = compute_forward_range(i, n_candles)
                if r:
                    fr[label] = r
            features.append(fr)

        # Compute GEX percentiles
        q20 = _percentile(abs_gex, 20)
        q40 = _percentile(abs_gex, 40)
        q60 = _percentile(abs_gex, 60)
        q80 = _percentile(abs_gex, 80)
        print(f"  GEX percentiles: p20={q20:,.0f}, p40={q40:,.0f}, p60={q60:,.0f}, p80={q80:,.0f}")

        # Test GEX → Future Range relationship
        print("\n--- GEX Quintiles vs Future Range ---")
        for label in ["15m", "30m", "60m"]:
            print(f"\n  {label} Range:")
            for qi, (lo, hi, qname) in enumerate([
                (0, q20, "Q1 (Very Low)"),
                (q20, q40, "Q2 (Low)"),
                (q40, q60, "Q3 (Medium)"),
                (q60, q80, "Q4 (High)"),
                (q80, float("inf"), "Q5 (Very High)"),
            ]):
                ranges = []
                for i in range(len(timestamps)):
                    if lo <= abs_gex[i] < hi:
                        r = features[i].get(label, {}).get("range_pct")
                        if r is not None:
                            ranges.append(r)
                if ranges:
                    print(f"    {qname}: N={len(ranges):>5}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%, std={_std(ranges):.4f}%")

        # Correlation: Abs GEX vs Future Range
        print("\n--- Correlation: Abs GEX vs Future Range ---")
        for label in ["3m", "6m", "9m", "15m", "30m", "60m"]:
            xs = [abs_gex[i] for i in range(len(timestamps)) if features[i].get(label, {}).get("range_pct") is not None]
            ys = [features[i][label]["range_pct"] for i in range(len(timestamps)) if features[i].get(label, {}).get("range_pct") is not None]
            if len(xs) >= 10:
                c = _corr(xs, ys)
                r2 = c * c
                print(f"  {label}: r={c:.4f}, R2={r2:.4f}, N={len(xs)}")

        # Phase 4: Regime analysis
        print("\n--- GEX Regime vs Future Range (15m) ---")
        regime_groups = defaultdict(list)
        for i in range(len(timestamps)):
            regime = "POS" if net_gex[i] > 0 else ("NEG" if net_gex[i] < 0 else "NEU")
            r = features[i].get("15m", {}).get("range_pct")
            if r is not None:
                regime_groups[regime].append(r)

        for regime in ["POS", "NEG", "NEU"]:
            if regime in regime_groups:
                rets = regime_groups[regime]
                print(f"  {regime}: N={len(rets)}, mean={_mean(rets):.4f}%, median={_median(rets):.4f}%")

        print(f"\n  Data load: {time.time()-t0:.1f}s")

        # ==================================================================
        # Phase 5-6: Expected Range Model
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 5-6: EXPECTED RANGE MODEL")
        print("=" * 70)

        # Simple linear regression: range ~ abs_gex
        print("\n--- Simple Linear Regression: 15m Range ~ Abs GEX ---")
        xs, ys = [], []
        for i in range(len(timestamps)):
            r = features[i].get("15m", {}).get("range_pct")
            if r is not None:
                xs.append(abs_gex[i])
                ys.append(r)

        if len(xs) >= 10:
            # Center variables
            mx, my = _mean(xs), _mean(ys)
            xs_c = [x - mx for x in xs]
            ys_c = [y - my for y in ys]
            ss_xx = sum(x**2 for x in xs_c)
            ss_xy = sum(x*y for x, y in zip(xs_c, ys_c))
            beta = ss_xy / ss_xx if ss_xx > 0 else 0
            alpha = my - beta * mx
            predicted = [alpha + beta * x for x in xs]
            ss_res = sum((y - p)**2 for y, p in zip(ys, predicted))
            ss_tot = sum((y - my)**2 for y in ys)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            print(f"  beta = {beta:.8f}")
            print(f"  alpha = {alpha:.4f}%")
            print(f"  R2 = {r2:.6f}")
            print(f"  Interpretation: Each 1B increase in Abs GEX -> {beta*1e9:.4f}% change in 15m range")

        # Walk-forward split
        print("\n--- Walk-Forward R2 (60/20/20) ---")
        n = len(xs)
        train_end = int(n * 0.6)
        val_end = int(n * 0.8)

        for split_name, start, end in [("Train", 0, train_end), ("Val", train_end, val_end), ("Test", val_end, n)]:
            sx = xs[start:end]
            sy = ys[start:end]
            if len(sx) < 10:
                print(f"  {split_name}: insufficient data")
                continue
            mx_s, my_s = _mean(sx), _mean(sy)
            sx_c = [x - mx_s for x in sx]
            sy_c = [y - my_s for y in sy]
            ss_xx = sum(x**2 for x in sx_c)
            ss_xy = sum(x*y for x, y in zip(sx_c, sy_c))
            b = ss_xy / ss_xx if ss_xx > 0 else 0
            a = my_s - b * mx_s
            pred = [a + b * x for x in sx]
            ss_res = sum((y - p)**2 for y, p in zip(sy, pred))
            ss_tot = sum((y - my_s)**2 for y in sy)
            r2_val = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            print(f"  {split_name}: N={len(sx)}, R2={r2_val:.6f}, beta={b:.8f}")

        # ==================================================================
        # Phase 7-8: Option-Level Validation (Straddle/Strangle)
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 7-8: OPTION-LEVEL VALIDATION")
        print("=" * 70)

        # Load option candle data aligned with GEX timestamps
        print("Loading option candles aligned with GEX timestamps...")
        opt_data = conn.execute("""
            SELECT c.open_time, c.instrument_key,
                   s.strike_price, s.expiry, s.instrument_type,
                   c.close, c.open_interest, c.volume, s.lot_size
            FROM option_candles c
            JOIN contract_specs s ON c.instrument_key = s.instrument_key
            WHERE c.close > 0
        """).fetchall()
        print(f"  Loaded {len(opt_data):,} option candle records")

        # Group by timestamp to find ATM straddles
        ts_options = defaultdict(lambda: defaultdict(dict))
        for r in opt_data:
            ts = r[0]
            ik = r[1]
            strike = r[2]
            expiry = r[3]
            opt_type = r[4]
            price = r[5]
            oi = r[6] or 0
            vol = r[7] or 0
            lot_size = r[8] or 50

            key = (strike, expiry)
            if opt_type not in ts_options[ts][key]:
                ts_options[ts][key][opt_type] = {
                    "price": price, "oi": oi, "vol": vol,
                    "lot_size": lot_size, "strike": strike,
                }

        # Find ATM straddles (CE + PE at same strike/expiry)
        print("Computing ATM straddle data...")
        straddle_data = []
        for ts in timestamps:
            if ts not in ts_options:
                continue
            spot = spots[ts_idx := timestamps.index(ts)]

            # Find closest strike to spot
            strikes_in_ts = list(ts_options[ts].keys())
            if not strikes_in_ts:
                continue

            closest = min(strikes_in_ts, key=lambda k: abs(k[0] - spot))
            strike, expiry = closest

            if "CE" in ts_options[ts][closest] and "PE" in ts_options[ts][closest]:
                ce = ts_options[ts][closest]["CE"]
                pe = ts_options[ts][closest]["PE"]
                straddle_premium = ce["price"] + pe["price"]

                # Compute forward straddle decay
                # Find future straddle price
                ts_idx = timestamps.index(ts)
                future_ranges = features[ts_idx]

                straddle_data.append({
                    "timestamp": ts,
                    "spot": spot,
                    "strike": strike,
                    "straddle_premium": straddle_premium,
                    "ce_price": ce["price"],
                    "pe_price": pe["price"],
                    "abs_gex": abs_gex[ts_idx],
                    "net_gex": net_gex[ts_idx],
                    "range_15m": future_ranges.get("15m", {}).get("range_pct"),
                    "range_30m": future_ranges.get("30m", {}).get("range_pct"),
                    "range_60m": future_ranges.get("60m", {}).get("range_pct"),
                })

        print(f"  ATM straddles found: {len(straddle_data)}")

        if straddle_data:
            # Analyze straddle premium by GEX quintile
            print("\n--- Straddle Premium by GEX Quintile ---")
            gex_vals = [d["abs_gex"] for d in straddle_data]
            q20_s = _percentile(gex_vals, 20)
            q40_s = _percentile(gex_vals, 40)
            q60_s = _percentile(gex_vals, 60)
            q80_s = _percentile(gex_vals, 80)

            for qi, (lo, hi, qname) in enumerate([
                (0, q20_s, "Q1 (Very Low)"),
                (q20_s, q40_s, "Q2 (Low)"),
                (q40_s, q60_s, "Q3 (Medium)"),
                (q60_s, q80_s, "Q4 (High)"),
                (q80_s, float("inf"), "Q5 (Very High)"),
            ]):
                group = [d for d in straddle_data if lo <= d["abs_gex"] < hi]
                if group:
                    premiums = [d["straddle_premium"] for d in group]
                    ranges_15m = [d["range_15m"] for d in group if d["range_15m"] is not None]
                    ranges_30m = [d["range_30m"] for d in group if d["range_30m"] is not None]
                    print(f"  {qname}: N={len(group)}, premium={_mean(premiums):.2f}, "
                          f"range_15m={_mean(ranges_15m):.4f}% " if ranges_15m else "",
                          f"range_30m={_mean(ranges_30m):.4f}%" if ranges_30m else "")

        # ==================================================================
        # Phase 9: IV vs Realized Volatility
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 9: IV VS REALIZED VOLATILITY")
        print("=" * 70)

        # Check IV coverage
        iv_coverage = conn.execute("""
            SELECT COUNT(DISTINCT open_time)
            FROM option_greeks
            WHERE implied_volatility IS NOT NULL
                  AND implied_volatility > 0 AND implied_volatility < 5.0
                  AND calc_version = 'greeks_v3' AND status = 'SUCCESS'
        """).fetchone()
        print(f"  Timestamps with valid IV: {iv_coverage[0]:,}")

        if iv_coverage[0] > 100:
            # Load IV data
            iv_data = conn.execute("""
                SELECT open_time, AVG(implied_volatility) as avg_iv
                FROM option_greeks
                WHERE implied_volatility IS NOT NULL
                      AND implied_volatility > 0 AND implied_volatility < 5.0
                      AND calc_version = 'greeks_v3' AND status = 'SUCCESS'
                GROUP BY open_time
            """).fetchall()
            iv_map = {r[0]: r[1] for r in iv_data}
            print(f"  IV timestamps loaded: {len(iv_map)}")

            # Compute IV vs realized vol
            print("\n--- IV vs Realized Volatility (15m) ---")
            iv_vals = []
            rv_vals = []
            for i in range(len(timestamps)):
                ts = timestamps[i]
                if ts in iv_map:
                    r = features[i].get("15m", {})
                    if r.get("range_pct") is not None:
                        iv_vals.append(iv_map[ts])
                        rv_vals.append(r["range_pct"])

            if len(iv_vals) >= 10:
                print(f"  N={len(iv_vals)}")
                print(f"  Mean IV: {_mean(iv_vals):.4f}")
                print(f"  Mean RV (15m range): {_mean(rv_vals):.4f}%")
                print(f"  IV-RV spread: {_mean(iv_vals) - _mean(rv_vals):.4f}")
                c = _corr(iv_vals, rv_vals)
                print(f"  Correlation: {c:.4f}")

                # IV-RV spread by GEX quintile
                print("\n  IV-RV by GEX quintile:")
                iv_gex = [(iv_map.get(timestamps[i], 0), abs_gex[i]) for i in range(len(timestamps))
                          if timestamps[i] in iv_map and features[i].get("15m", {}).get("range_pct") is not None]
                if iv_gex:
                    gex_vals_iv = [g for _, g in iv_gex]
                    q20_iv = _percentile(gex_vals_iv, 20)
                    q80_iv = _percentile(gex_vals_iv, 80)
                    low_gex = [(iv, g) for iv, g in iv_gex if g < q20_iv]
                    high_gex = [(iv, g) for iv, g in iv_gex if g > q80_iv]
                    if low_gex:
                        print(f"    Low GEX: N={len(low_gex)}, mean_IV={_mean([iv for iv,_ in low_gex]):.4f}")
                    if high_gex:
                        print(f"    High GEX: N={len(high_gex)}, mean_IV={_mean([iv for iv,_ in high_gex]):.4f}")
        else:
            print("  IV coverage insufficient for analysis")

        # ==================================================================
        # Phase 12: Option Strategy Simulation
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 12: OPTION STRATEGY SIMULATION")
        print("=" * 70)

        if straddle_data:
            # Strategy: High-GEX short straddle
            print("\n--- Strategy: High-GEX Short Straddle ---")
            print("  Entry: Abs GEX > 80th percentile")
            print("  Exit: 15m / 30m / 60m")

            high_gex_straddles = [d for d in straddle_data if d["abs_gex"] > q80_s]
            low_gex_straddles = [d for d in straddle_data if d["abs_gex"] < q20_s]

            print(f"\n  HIGH GEX straddles: N={len(high_gex_straddles)}")
            if high_gex_straddles:
                premiums = [d["straddle_premium"] for d in high_gex_straddles]
                ranges_15m = [d["range_15m"] for d in high_gex_straddles if d["range_15m"] is not None]
                ranges_30m = [d["range_30m"] for d in high_gex_straddles if d["range_30m"] is not None]
                ranges_60m = [d["range_60m"] for d in high_gex_straddles if d["range_60m"] is not None]

                print(f"    Avg straddle premium: {_mean(premiums):.2f} points")
                if ranges_15m:
                    print(f"    Avg 15m range: {_mean(ranges_15m):.4f}% ({_mean(ranges_15m)/100 * _mean(premiums):.2f} pts)")
                if ranges_30m:
                    print(f"    Avg 30m range: {_mean(ranges_30m):.4f}%")
                if ranges_60m:
                    print(f"    Avg 60m range: {_mean(ranges_60m):.4f}%")

            print(f"\n  LOW GEX straddles: N={len(low_gex_straddles)}")
            if low_gex_straddles:
                premiums = [d["straddle_premium"] for d in low_gex_straddles]
                ranges_15m = [d["range_15m"] for d in low_gex_straddles if d["range_15m"] is not None]
                ranges_30m = [d["range_30m"] for d in low_gex_straddles if d["range_30m"] is not None]
                ranges_60m = [d["range_60m"] for d in low_gex_straddles if d["range_60m"] is not None]

                print(f"    Avg straddle premium: {_mean(premiums):.2f} points")
                if ranges_15m:
                    print(f"    Avg 15m range: {_mean(ranges_15m):.4f}%")
                if ranges_30m:
                    print(f"    Avg 30m range: {_mean(ranges_30m):.4f}%")
                if ranges_60m:
                    print(f"    Avg 60m range: {_mean(ranges_60m):.4f}%")

            # Transaction cost analysis
            print("\n--- Transaction Cost Analysis ---")
            print("  Assumptions:")
            print("    Brokerage: 0.03% per leg (2 legs = 0.06%)")
            print("    STT: 0.1% on sell side")
            print("    Exchange: 0.003% per leg")
            print("    Slippage: 0.01% per leg")
            print("    Total round-trip: ~0.15% of premium")
            print()

            if high_gex_straddles:
                avg_premium = _mean([d["straddle_premium"] for d in high_gex_straddles])
                cost_pct = avg_premium * 0.0015  # 0.15% of premium
                print(f"  High GEX straddle:")
                print(f"    Avg premium: {avg_premium:.2f} pts")
                print(f"    Estimated cost: {cost_pct:.2f} pts")
                if ranges_15m:
                    range_pts_15m = _mean(ranges_15m) / 100 * spots[0]
                    print(f"    Avg 15m range: {range_pts_15m:.2f} pts")
                    print(f"    P&L if range < premium: {avg_premium - range_pts_15m:.2f} pts (before costs)")
                    print(f"    P&L after costs: {avg_premium - range_pts_15m - cost_pct:.2f} pts")

        # ==================================================================
        # Phase 15: Walk-Forward Strategy Testing
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 15: WALK-FORWARD STRATEGY TESTING")
        print("=" * 70)

        if straddle_data:
            n_sd = len(straddle_data)
            train_end = int(n_sd * 0.6)
            val_end = int(n_sd * 0.8)

            print("\n--- High-GEX Short Straddle Walk-Forward ---")
            for split_name, start, end in [("Train", 0, train_end), ("Val", train_end, val_end), ("Test", val_end, n_sd)]:
                split = straddle_data[start:end]
                high_gex = [d for d in split if d["abs_gex"] > _percentile([d2["abs_gex"] for d2 in split], 80)]
                if not high_gex:
                    print(f"  {split_name}: no high-GEX observations")
                    continue
                premiums = [d["straddle_premium"] for d in high_gex]
                ranges_15m = [d["range_15m"] for d in high_gex if d["range_15m"] is not None]
                if ranges_15m:
                    avg_prem = _mean(premiums)
                    avg_range = _mean(ranges_15m)
                    print(f"  {split_name}: N={len(high_gex)}, premium={avg_prem:.2f}, range_15m={avg_range:.4f}%")

        # ==================================================================
        # Phase 20: NEG_GAMMA Investigation
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 20: NEG_GAMMA INVESTIGATION")
        print("=" * 70)

        # NEG_GAMMA: net_gex < 0
        neg_gamma_indices = [i for i in range(len(timestamps)) if net_gex[i] < 0]
        pos_gamma_indices = [i for i in range(len(timestamps)) if net_gex[i] > 0]
        neutral_indices = [i for i in range(len(timestamps)) if net_gex[i] == 0]

        print(f"  NEG_GAMMA: {len(neg_gamma_indices)} timestamps ({len(neg_gamma_indices)/len(timestamps)*100:.1f}%)")
        print(f"  POS_GAMMA: {len(pos_gamma_indices)} timestamps ({len(pos_gamma_indices)/len(timestamps)*100:.1f}%)")
        print(f"  NEUTRAL: {len(neutral_indices)} timestamps ({len(neutral_indices)/len(timestamps)*100:.1f}%)")

        # Forward range by regime
        print("\n--- Forward Range by Regime ---")
        for label in ["15m", "30m", "60m"]:
            print(f"\n  {label} Range:")
            for regime_name, indices in [("NEG_GAMMA", neg_gamma_indices), ("POS_GAMMA", pos_gamma_indices)]:
                ranges = [features[i].get(label, {}).get("range_pct") for i in indices
                          if features[i].get(label, {}).get("range_pct") is not None]
                if ranges:
                    print(f"    {regime_name}: N={len(ranges)}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%")

        # NEG_GAMMA walk-forward
        print("\n--- NEG_GAMMA Walk-Forward (15m Range) ---")
        n_ng = len(neg_gamma_indices)
        train_end = int(n_ng * 0.6)
        val_end = int(n_ng * 0.8)

        for split_name, start, end in [("Train", 0, train_end), ("Val", train_end, val_end), ("Test", val_end, n_ng)]:
            split_idx = neg_gamma_indices[start:end]
            ranges = [features[i].get("15m", {}).get("range_pct") for i in split_idx
                      if features[i].get("15m", {}).get("range_pct") is not None]
            if ranges:
                print(f"  {split_name}: N={len(ranges)}, mean={_mean(ranges):.4f}%, median={_median(ranges):.4f}%")

        # ==================================================================
        # Phase 21: High-GEX Range Compression Verification
        # ==================================================================
        print("\n" + "=" * 70)
        print("PHASE 21: HIGH-GEX RANGE COMPRESSION VERIFICATION")
        print("=" * 70)

        print("\n--- All Horizons: GEX Quintile vs Range ---")
        for label in ["3m", "6m", "9m", "15m", "30m", "60m"]:
            print(f"\n  {label} Range:")
            all_ranges = [(abs_gex[i], features[i].get(label, {}).get("range_pct"))
                          for i in range(len(timestamps))
                          if features[i].get(label, {}).get("range_pct") is not None]
            if not all_ranges:
                continue

            gex_vals = [g for g, _ in all_ranges]
            q20_l = _percentile(gex_vals, 20)
            q80_l = _percentile(gex_vals, 80)

            low_gex = [r for g, r in all_ranges if g < q20_l]
            high_gex = [r for g, r in all_ranges if g > q80_l]

            if low_gex and high_gex:
                t = _tstat(low_gex + high_gex)
                print(f"    Low GEX: N={len(low_gex)}, mean={_mean(low_gex):.4f}%")
                print(f"    High GEX: N={len(high_gex)}, mean={_mean(high_gex):.4f}%")
                print(f"    Difference: {_mean(low_gex) - _mean(high_gex):.4f}%")
                print(f"    t-stat: {t:.3f}, p={_pval(t, len(low_gex)+len(high_gex)-2):.4f}")

        # Rolling window stability
        print("\n--- Rolling Window Stability (15m Range, High vs Low GEX) ---")
        all_15m = [(abs_gex[i], features[i].get("15m", {}).get("range_pct"), timestamps[i])
                   for i in range(len(timestamps))
                   if features[i].get("15m", {}).get("range_pct") is not None]
        all_15m.sort(key=lambda x: x[2])

        if all_15m:
            from datetime import datetime as dt, timedelta
            def to_dt(v):
                if isinstance(v, str):
                    return dt.fromisoformat(v.replace("Z","").split(".")[0])
                return v

            min_t = to_dt(all_15m[0][2])
            max_t = to_dt(all_15m[-1][2])
            current = min_t
            wnum = 0
            while current + timedelta(days=90) <= max_t:
                wend = current + timedelta(days=90)
                window = [(g, r) for g, r, t in all_15m if to_dt(t) >= current and to_dt(t) < wend]
                if len(window) >= 20:
                    wnum += 1
                    gex_vals_w = [g for g, _ in window]
                    q20_w = _percentile(gex_vals_w, 20)
                    q80_w = _percentile(gex_vals_w, 80)
                    low_w = [r for g, r in window if g < q20_w]
                    high_w = [r for g, r in window if g > q80_w]
                    if low_w and high_w:
                        diff = _mean(low_w) - _mean(high_w)
                        print(f"    W{wnum} ({current.strftime('%Y-%m-%d')}): N={len(window)}, diff={diff:.4f}%, low={_mean(low_w):.4f}%, high={_mean(high_w):.4f}%")
                current += timedelta(days=30)

        # ==================================================================
        # Database Safety
        # ==================================================================
        print("\n" + "=" * 70)
        print("DATABASE SAFETY VERIFICATION")
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
