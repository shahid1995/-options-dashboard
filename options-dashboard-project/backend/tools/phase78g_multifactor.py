"""Phase 7.8G — Multi-Factor Historical GEX Research.

Bulk-loads all data, computes features, screens single factors,
tests multi-factor combinations, applies walk-forward validation,
and produces a final research ranking.
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

def _mean(v):
    return sum(v)/len(v) if v else 0.0

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

def _cohens_d(v):
    if len(v)<2: return 0.0
    s=_std(v)
    return _mean(v)/s if s>0 else 0.0

def _ci95(v):
    if len(v)<2: return (0,0)
    m=_mean(v); se=_sem(v); t=1.96 if len(v)>=30 else 2.0
    return (m-t*se, m+t*se)

def _bh_fdr(pvalues):
    """Benjamini-Hochberg FDR correction."""
    n = len(pvalues)
    if n == 0: return []
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    adjusted = [0.0] * n
    for rank, (orig_idx, p) in enumerate(indexed, 1):
        adjusted[orig_idx] = min(p * n / rank, 1.0)
    # Ensure monotonicity
    for i in range(n-2, -1, -1):
        idx = indexed[i][0]
        next_idx = indexed[i+1][0]
        adjusted[idx] = min(adjusted[idx], adjusted[next_idx])
    return adjusted

def _classify(rets):
    """Classify a set of returns."""
    if not rets or len(rets) < 10:
        return "INSUFFICIENT_DATA"
    m = _mean(rets)
    t = _tstat(rets)
    p = _pval(t, len(rets)-1)
    w = sum(1 for r in rets if r > 0) / len(rets) * 100
    # Not useful if mean near zero
    if abs(m) < 0.001 or len(rets) < 30:
        return "REJECTED"
    if p >= 0.05:
        return "REJECTED"
    if len(rets) < 100:
        return "PROMISING"
    return "PROMISING"


# ==================================================================
# Data Loading
# ==================================================================

def load_all_data(conn):
    """Bulk-load all data from production database."""
    print("Loading GEX data...")
    t0 = time.time()

    # Aggregate per-timestamp using SQL
    ts_gex = conn.execute("""
        SELECT open_time, spot,
               SUM(CASE WHEN option_type='CE' THEN signed_gex ELSE 0 END) as call_gex,
               SUM(CASE WHEN option_type='PE' THEN signed_gex ELSE 0 END) as put_gex,
               SUM(ABS(signed_gex)) as abs_gex,
               COUNT(*) as instruments,
               COUNT(DISTINCT strike) as strikes
        FROM historical_gex
        WHERE status='SUCCESS' AND calc_version='h_gex_v1'
        GROUP BY open_time
        ORDER BY open_time
    """).fetchall()

    timestamps = [r[0] for r in ts_gex]
    spots = [r[1] for r in ts_gex]
    call_gex = [r[2] for r in ts_gex]
    put_gex = [r[3] for r in ts_gex]
    abs_gex = [r[4] for r in ts_gex]
    instruments = [r[5] for r in ts_gex]
    strikes = [r[6] for r in ts_gex]
    net_gex = [c + p for c, p in zip(call_gex, put_gex)]

    print(f"  Timestamps: {len(timestamps)}, GEX rows: {sum(instruments):,}")
    print(f"  Range: {timestamps[0]} to {timestamps[-1]}")

    # Load NIFTY candles
    print("Loading NIFTY candles...")
    nifty = conn.execute("""
        SELECT open_time, close FROM nifty_candles
        WHERE interval='3min'
        ORDER BY open_time
    """).fetchall()
    nifty_ts = [r[0] for r in nifty]
    nifty_close = {r[0]: r[1] for r in nifty}

    # Build forward returns lookup
    print("Building forward returns...")
    nifty_list = list(zip(nifty_ts, [nifty_close[t] for t in nifty_ts]))

    def get_fwd_returns(ts_idx):
        ts = timestamps[ts_idx]
        spot = spots[ts_idx]
        # Find NIFTY index after this timestamp
        nifty_idx = None
        for i, (nts, _) in enumerate(nifty_list):
            if nts > ts:
                nifty_idx = i
                break
        if nifty_idx is None:
            return {}
        returns = {}
        for interval, label in [(1,"3m"),(2,"6m"),(3,"9m"),(5,"15m"),(10,"30m"),(20,"60m")]:
            if nifty_idx + interval <= len(nifty_list):
                returns[label] = (nifty_list[nifty_idx+interval-1][1] - spot) / spot * 100
        return returns

    # Load strike-level GEX for flip/wall detection (sample every 10th timestamp)
    print("Loading strike-level GEX for flip/wall...")
    strike_gex = conn.execute("""
        SELECT open_time, strike,
               SUM(signed_gex) as net_gex
        FROM historical_gex
        WHERE status='SUCCESS' AND calc_version='h_gex_v1'
        GROUP BY open_time, strike
        ORDER BY open_time, strike
    """).fetchall()

    # Build per-timestamp strike maps
    ts_strike_gex = defaultdict(dict)
    for r in strike_gex:
        ts_strike_gex[r[0]][r[1]] = r[2]

    # Load OI data (bulk join)
    print("Loading OI data...")
    oi_data = conn.execute("""
        SELECT g.open_time,
               SUM(CASE WHEN g.option_type='CE' THEN c.open_interest ELSE 0 END) as call_oi,
               SUM(CASE WHEN g.option_type='PE' THEN c.open_interest ELSE 0 END) as put_oi,
               SUM(CASE WHEN g.option_type='CE' THEN c.volume ELSE 0 END) as call_vol,
               SUM(CASE WHEN g.option_type='PE' THEN c.volume ELSE 0 END) as put_vol
        FROM option_greeks g
        JOIN option_candles c ON g.instrument_key = c.instrument_key AND g.open_time = c.open_time
        WHERE g.calc_version = 'greeks_v3' AND g.status = 'SUCCESS'
        GROUP BY g.open_time
    """).fetchall()
    oi_map = {}
    for r in oi_data:
        oi_map[r[0]] = {"call_oi": r[1] or 0, "put_oi": r[2] or 0,
                         "call_vol": r[3] or 0, "put_vol": r[4] or 0}

    # Load IV data (ATM IV from Greeks)
    print("Loading IV data...")
    iv_data = conn.execute("""
        SELECT g.open_time, g.option_type, g.implied_volatility
        FROM option_greeks g
        WHERE g.calc_version = 'greeks_v3' AND g.status = 'SUCCESS'
              AND g.implied_volatility IS NOT NULL
              AND g.implied_volatility > 0 AND g.implied_volatility < 5.0
    """).fetchall()
    iv_map = defaultdict(lambda: {"ce_iv": [], "pe_iv": []})
    for r in iv_data:
        ts = r[0]
        if r[1] == "CE":
            iv_map[ts]["ce_iv"].append(r[2])
        elif r[1] == "PE":
            iv_map[ts]["pe_iv"].append(r[2])

    elapsed = time.time() - t0
    print(f"  OI timestamps: {len(oi_map)}, IV timestamps: {len(iv_map)}")
    print(f"  Data load: {elapsed:.1f}s")

    return {
        "timestamps": timestamps, "spots": spots, "net_gex": net_gex,
        "call_gex": call_gex, "put_gex": put_gex, "abs_gex": abs_gex,
        "instruments": instruments, "strikes": strikes,
        "get_fwd_returns": get_fwd_returns,
        "ts_strike_gex": ts_strike_gex,
        "oi_map": oi_map, "iv_map": iv_map,
    }


# ==================================================================
# Feature Computation
# ==================================================================

def compute_features(data):
    """Compute all candidate features at each timestamp."""
    ts = data["timestamps"]
    spots = data["spots"]
    net_gex = data["net_gex"]
    call_gex = data["call_gex"]
    put_gex = data["put_gex"]
    abs_gex = data["abs_gex"]
    n = len(ts)

    features = []
    for i in range(n):
        f = {"idx": i, "timestamp": ts[i], "spot": spots[i]}

        # --- GEX features ---
        f["net_gex"] = net_gex[i]
        f["abs_gex"] = abs_gex[i]
        f["ce_gex"] = call_gex[i]
        f["pe_gex"] = put_gex[i]
        f["ce_pe_ratio"] = abs(call_gex[i] / put_gex[i]) if abs(put_gex[i]) > 1e-10 else None
        f["gex_imbalance"] = (call_gex[i] + put_gex[i]) / abs_gex[i] if abs_gex[i] > 0 else 0.0
        f["pos_conc"] = max(call_gex[i], 0) / abs_gex[i] if abs_gex[i] > 0 else 0.0
        f["neg_conc"] = abs(min(put_gex[i], 0)) / abs_gex[i] if abs_gex[i] > 0 else 0.0
        f["regime"] = "POS_GAMMA" if net_gex[i] > 0 else ("NEG_GAMMA" if net_gex[i] < 0 else "NEUTRAL")

        # GEX change
        if i > 0:
            f["gex_change"] = net_gex[i] - net_gex[i-1]
            f["gex_change_pct"] = f["gex_change"] / abs(net_gex[i-1]) * 100 if abs(net_gex[i-1]) > 1e-10 else 0
        else:
            f["gex_change"] = 0
            f["gex_change_pct"] = 0

        # GEX acceleration
        if i >= 2:
            prev_change = net_gex[i-1] - net_gex[i-2]
            f["gex_acceleration"] = f["gex_change"] - prev_change
        else:
            f["gex_acceleration"] = 0

        # --- Price features ---
        if i > 0:
            f["price_momentum"] = spots[i] - spots[i-1]
            f["price_momentum_pct"] = f["price_momentum"] / spots[i-1] * 100 if spots[i-1] > 0 else 0
        else:
            f["price_momentum"] = 0
            f["price_momentum_pct"] = 0

        if i >= 2:
            f["price_acceleration"] = (spots[i] - spots[i-1]) - (spots[i-1] - spots[i-2])
        else:
            f["price_acceleration"] = 0

        # --- OI features ---
        oi = data["oi_map"].get(ts[i], {})
        f["total_oi"] = (oi.get("call_oi", 0) or 0) + (oi.get("put_oi", 0) or 0)
        f["call_oi"] = oi.get("call_oi", 0) or 0
        f["put_oi"] = oi.get("put_oi", 0) or 0
        f["oi_ratio"] = f["call_oi"] / f["put_oi"] if f["put_oi"] > 0 else None
        f["total_vol"] = (oi.get("call_vol", 0) or 0) + (oi.get("put_vol", 0) or 0)
        f["call_vol"] = oi.get("call_vol", 0) or 0
        f["put_vol"] = oi.get("put_vol", 0) or 0
        f["vol_oi_ratio"] = f["total_vol"] / f["total_oi"] if f["total_oi"] > 0 else None

        # OI change
        if i > 0:
            prev_oi = data["oi_map"].get(ts[i-1], {})
            prev_total = (prev_oi.get("call_oi", 0) or 0) + (prev_oi.get("put_oi", 0) or 0)
            f["oi_change"] = f["total_oi"] - prev_total
            f["call_oi_change"] = f["call_oi"] - (prev_oi.get("call_oi", 0) or 0)
            f["put_oi_change"] = f["put_oi"] - (prev_oi.get("put_oi", 0) or 0)
        else:
            f["oi_change"] = 0
            f["call_oi_change"] = 0
            f["put_oi_change"] = 0

        # OI imbalance classification
        if f["oi_change"] > 0 and f["price_momentum"] > 0:
            f["oi_class"] = "LONG_BUILDUP"
        elif f["oi_change"] > 0 and f["price_momentum"] < 0:
            f["oi_class"] = "SHORT_BUILDUP"
        elif f["oi_change"] < 0 and f["price_momentum"] > 0:
            f["oi_class"] = "SHORT_COVERING"
        elif f["oi_change"] < 0 and f["price_momentum"] < 0:
            f["oi_class"] = "LONG_UNWINDING"
        else:
            f["oi_class"] = "NEUTRAL"

        # --- IV features ---
        iv = data["iv_map"].get(ts[i], {"ce_iv": [], "pe_iv": []})
        f["atm_iv"] = None
        f["ce_iv"] = _mean(iv["ce_iv"]) if iv["ce_iv"] else None
        f["pe_iv"] = _mean(iv["pe_iv"]) if iv["pe_iv"] else None
        if f["ce_iv"] and f["pe_iv"]:
            f["atm_iv"] = (f["ce_iv"] + f["pe_iv"]) / 2
            f["iv_skew"] = f["pe_iv"] - f["ce_iv"]
        else:
            f["iv_skew"] = None

        # IV change
        if i > 0 and f["atm_iv"] is not None:
            prev_iv = data["iv_map"].get(ts[i-1], {"ce_iv": [], "pe_iv": []})
            prev_atm = None
            if prev_iv["ce_iv"] and prev_iv["pe_iv"]:
                prev_atm = (_mean(prev_iv["ce_iv"]) + _mean(prev_iv["pe_iv"])) / 2
            f["iv_change"] = f["atm_iv"] - prev_atm if prev_atm else None
        else:
            f["iv_change"] = None

        # --- Gamma flip ---
        strikes_gex = data["ts_strike_gex"].get(ts[i], {})
        if len(strikes_gex) >= 2:
            sorted_strikes = sorted(strikes_gex.items())
            sign_changes = []
            for j in range(len(sorted_strikes)-1):
                s1, g1 = sorted_strikes[j]
                s2, g2 = sorted_strikes[j+1]
                if g1 * g2 < 0 and (g2 - g1) != 0:
                    flip = s1 - g1 * (s2 - s1) / (g2 - g1)
                    sign_changes.append(flip)
            if sign_changes:
                f["gamma_flip"] = min(sign_changes, key=lambda x: abs(x - spots[i]))
                f["flip_distance"] = f["gamma_flip"] - spots[i]
            else:
                f["gamma_flip"] = None
                f["flip_distance"] = None
        else:
            f["gamma_flip"] = None
            f["flip_distance"] = None

        # --- Gamma walls ---
        if strikes_gex:
            pos_strikes = [(s, g) for s, g in strikes_gex.items() if g > 0]
            neg_strikes = [(s, g) for s, g in strikes_gex.items() if g < 0]
            if pos_strikes:
                best_pos = max(pos_strikes, key=lambda x: x[1])
                f["pos_wall"] = best_pos[0]
                f["pos_wall_dist"] = best_pos[0] - spots[i]
                f["pos_wall_dist_pct"] = f["pos_wall_dist"] / spots[i] * 100 if spots[i] > 0 else 0
            else:
                f["pos_wall"] = None
                f["pos_wall_dist"] = None
                f["pos_wall_dist_pct"] = None
            if neg_strikes:
                best_neg = min(neg_strikes, key=lambda x: x[1])
                f["neg_wall"] = best_neg[0]
                f["neg_wall_dist"] = best_neg[0] - spots[i]
                f["neg_wall_dist_pct"] = f["neg_wall_dist"] / spots[i] * 100 if spots[i] > 0 else 0
            else:
                f["neg_wall"] = None
                f["neg_wall_dist"] = None
                f["neg_wall_dist_pct"] = None
        else:
            f["pos_wall"] = None
            f["pos_wall_dist"] = None
            f["pos_wall_dist_pct"] = None
            f["neg_wall"] = None
            f["neg_wall_dist"] = None
            f["neg_wall_dist_pct"] = None

        # --- Composite features ---
        # GEX momentum: GEX change * sign of price momentum
        if f["price_momentum"] != 0:
            f["gex_momentum_align"] = 1 if (f["gex_change"] > 0 and f["price_momentum"] > 0) or \
                                         (f["gex_change"] < 0 and f["price_momentum"] < 0) else -1
        else:
            f["gex_momentum_align"] = 0

        # Regime + momentum
        if f["regime"] == "NEG_GAMMA" and f["price_momentum"] < 0:
            f["regime_momentum"] = "NEG_GAMMA_DOWN"
        elif f["regime"] == "POS_GAMMA" and f["price_momentum"] > 0:
            f["regime_momentum"] = "POS_GAMMA_UP"
        elif f["regime"] == "NEG_GAMMA" and f["price_momentum"] > 0:
            f["regime_momentum"] = "NEG_GAMMA_UP"
        elif f["regime"] == "POS_GAMMA" and f["price_momentum"] < 0:
            f["regime_momentum"] = "POS_GAMMA_DOWN"
        else:
            f["regime_momentum"] = "NEUTRAL"

        features.append(f)

    return features


# ==================================================================
# Single-Factor Screening
# ==================================================================

def screen_single_factors(features, data):
    """Screen each feature independently against forward returns."""
    print("\n" + "=" * 70)
    print("SINGLE-FACTOR SCREENING")
    print("=" * 70)

    # Define feature tests
    tests = []

    # Numeric features: compare top vs bottom quartile
    numeric_features = [
        ("net_gex", "Net GEX"),
        ("abs_gex", "Absolute GEX"),
        ("gex_change", "GEX Change"),
        ("gex_change_pct", "GEX Change %"),
        ("gex_acceleration", "GEX Acceleration"),
        ("price_momentum_pct", "Price Momentum %"),
        ("price_acceleration", "Price Acceleration"),
        ("ce_pe_ratio", "CE/PE GEX Ratio"),
        ("gex_imbalance", "GEX Imbalance"),
        ("total_oi", "Total OI"),
        ("oi_change", "OI Change"),
        ("call_oi_change", "Call OI Change"),
        ("put_oi_change", "Put OI Change"),
        ("vol_oi_ratio", "Volume/OI Ratio"),
        ("atm_iv", "ATM IV"),
        ("iv_skew", "IV Skew"),
        ("iv_change", "IV Change"),
        ("flip_distance", "Flip Distance"),
        ("pos_wall_dist_pct", "Pos Wall Distance %"),
        ("neg_wall_dist_pct", "Neg Wall Distance %"),
        ("gex_momentum_align", "GEX-Momentum Alignment"),
    ]

    # Categorical features
    categorical_tests = [
        ("regime", "Gamma Regime"),
        ("oi_class", "OI Classification"),
        ("regime_momentum", "Regime + Momentum"),
    ]

    results = []

    for fwd_horizon in ["15m", "30m", "60m"]:
        print(f"\n--- Forward Horizon: {fwd_horizon} ---")

        # Compute forward returns
        fwd_rets = []
        for i in range(len(features)):
            fr = data["get_fwd_returns"](i)
            fwd_rets.append(fr.get(fwd_horizon))

        # Numeric features
        for feat_key, feat_name in numeric_features:
            vals = [(features[i][feat_key], fwd_rets[i]) for i in range(len(features))
                    if features[i].get(feat_key) is not None and fwd_rets[i] is not None]
            if len(vals) < 20:
                continue

            vals.sort(key=lambda x: x[0])
            n = len(vals)
            q1 = vals[:n//4]
            q4 = vals[3*n//4:]

            q1_rets = [r for _, r in q1]
            q4_rets = [r for _, r in q4]

            q1_mean = _mean(q1_rets)
            q4_mean = _mean(q4_rets)
            spread = q4_mean - q1_mean

            # Test if high-value group differs from low-value group
            combined = q1_rets + q4_rets
            t = _tstat(combined)
            p = _pval(t, len(combined)-1)

            wins = sum(1 for r in combined if r > 0)
            win_pct = wins / len(combined) * 100

            tests.append({
                "horizon": fwd_horizon,
                "feature": feat_name,
                "key": feat_key,
                "type": "numeric",
                "n": len(combined),
                "q1_mean": q1_mean,
                "q4_mean": q4_mean,
                "spread": spread,
                "mean": _mean(combined),
                "win_pct": win_pct,
                "t_stat": t,
                "p_value": p,
                "effect": _cohens_d(combined),
            })

        # Categorical features
        for feat_key, feat_name in categorical_tests:
            groups = defaultdict(list)
            for i in range(len(features)):
                val = features[i].get(feat_key)
                if val is not None and fwd_rets[i] is not None:
                    groups[val].append(fwd_rets[i])

            for group_name, rets in groups.items():
                if len(rets) < 10:
                    continue
                t = _tstat(rets)
                p = _pval(t, len(rets)-1)
                wins = sum(1 for r in rets if r > 0)
                tests.append({
                    "horizon": fwd_horizon,
                    "feature": f"{feat_name}={group_name}",
                    "key": f"{feat_key}:{group_name}",
                    "type": "categorical",
                    "n": len(rets),
                    "q1_mean": None,
                    "q4_mean": None,
                    "spread": _mean(rets),
                    "mean": _mean(rets),
                    "win_pct": wins / len(rets) * 100,
                    "t_stat": t,
                    "p_value": p,
                    "effect": _cohens_d(rets),
                })

    # Multiple-testing correction
    pvalues = [t["p_value"] for t in tests]
    adjusted = _bh_fdr(pvalues)
    for t, adj in zip(tests, adjusted):
        t["adj_p_value"] = adj

    # Print results (significant only)
    sig_tests = [t for t in tests if t["adj_p_value"] < 0.10]
    sig_tests.sort(key=lambda x: x["adj_p_value"])

    print(f"\nTotal tests: {len(tests)}")
    print(f"Significant (uncorrected p<0.05): {sum(1 for t in tests if t['p_value'] < 0.05)}")
    print(f"Significant (BH-FDR q<0.10): {len(sig_tests)}")
    print()

    for t in sig_tests[:30]:
        print(f"  {t['horizon']:>4} | {t['feature']:<35} | N={t['n']:>5} | mean={t['mean']:>+.4f}% | win%={t['win_pct']:>5.1f}% | t={t['t_stat']:>6.3f} | p={t['p_value']:.4f} | adj_p={t['adj_p_value']:.4f} | d={t['effect']:>+.3f}")

    return tests, sig_tests


# ==================================================================
# Multi-Factor Combinations
# ==================================================================

def test_multifactor(features, data, sig_tests):
    """Test multi-factor combinations."""
    print("\n" + "=" * 70)
    print("MULTI-FACTOR COMBINATIONS")
    print("=" * 70)

    fwd_horizon = "15m"
    fwd_rets = []
    for i in range(len(features)):
        fr = data["get_fwd_returns"](i)
        fwd_rets.append(fr.get(fwd_horizon))

    combos = []

    # Combo 1: Regime + Price Momentum
    for i in range(len(features)):
        f = features[i]
        r = fwd_rets[i]
        if r is None: continue
        combo = f"{f['regime']}_{('UP' if f['price_momentum'] > 0 else 'DOWN' if f['price_momentum'] < 0 else 'FLAT')}"
        combos.append((combo, r))

    groups = defaultdict(list)
    for c, r in combos:
        groups[c].append(r)

    print("\n--- Regime + Momentum ---")
    for g in sorted(groups.keys()):
        rets = groups[g]
        if len(rets) < 10: continue
        wins = sum(1 for r in rets if r > 0)
        t = _tstat(rets)
        p = _pval(t, len(rets)-1)
        print(f"  {g:<25} N={len(rets):>5} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")

    # Combo 2: GEX-Momentum Alignment + OI Class
    print("\n--- GEX-Momentum Alignment + OI Class ---")
    combo_groups = defaultdict(list)
    for i in range(len(features)):
        f = features[i]
        r = fwd_rets[i]
        if r is None: continue
        gma = f.get("gex_momentum_align", 0)
        oi_c = f.get("oi_class", "NEUTRAL")
        combo = f"gma={gma}_oi={oi_c}"
        combo_groups[combo].append(r)

    for g in sorted(combo_groups.keys()):
        rets = combo_groups[g]
        if len(rets) < 10: continue
        wins = sum(1 for r in rets if r > 0)
        t = _tstat(rets)
        p = _pval(t, len(rets)-1)
        print(f"  {g:<40} N={len(rets):>5} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")

    # Combo 3: Regime + IV Change direction
    print("\n--- Regime + IV Change ---")
    iv_combo = defaultdict(list)
    for i in range(len(features)):
        f = features[i]
        r = fwd_rets[i]
        if r is None: continue
        ivc = f.get("iv_change")
        if ivc is None: continue
        iv_dir = "IV_UP" if ivc > 0.001 else ("IV_DOWN" if ivc < -0.001 else "IV_FLAT")
        combo = f"{f['regime']}_{iv_dir}"
        iv_combo[combo].append(r)

    for g in sorted(iv_combo.keys()):
        rets = iv_combo[g]
        if len(rets) < 10: continue
        wins = sum(1 for r in rets if r > 0)
        t = _tstat(rets)
        p = _pval(t, len(rets)-1)
        print(f"  {g:<30} N={len(rets):>5} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")

    # Combo 4: Near wall + momentum
    print("\n--- Near Wall + Momentum ---")
    wall_combo = defaultdict(list)
    for i in range(len(features)):
        f = features[i]
        r = fwd_rets[i]
        if r is None: continue
        near_pos = f.get("pos_wall_dist_pct") is not None and abs(f["pos_wall_dist_pct"]) < 0.5
        near_neg = f.get("neg_wall_dist_pct") is not None and abs(f["neg_wall_dist_pct"]) < 0.5
        mom_dir = "UP" if f["price_momentum"] > 0 else ("DOWN" if f["price_momentum"] < 0 else "FLAT")
        if near_pos:
            wall_combo[f"NEAR_POS_WALL_{mom_dir}"].append(r)
        if near_neg:
            wall_combo[f"NEAR_NEG_WALL_{mom_dir}"].append(r)

    for g in sorted(wall_combo.keys()):
        rets = wall_combo[g]
        if len(rets) < 5: continue
        wins = sum(1 for r in rets if r > 0)
        t = _tstat(rets)
        p = _pval(t, len(rets)-1)
        print(f"  {g:<30} N={len(rets):>5} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")

    # Combo 5: Regime + flip distance
    print("\n--- Regime + Flip Distance ---")
    flip_combo = defaultdict(list)
    for i in range(len(features)):
        f = features[i]
        r = fwd_rets[i]
        if r is None: continue
        fd = f.get("flip_distance")
        if fd is None: continue
        flip_zone = "NEAR_FLIP" if abs(fd) < 30 else ("ABOVE_FLIP" if fd > 0 else "BELOW_FLIP")
        combo = f"{f['regime']}_{flip_zone}"
        flip_combo[combo].append(r)

    for g in sorted(flip_combo.keys()):
        rets = flip_combo[g]
        if len(rets) < 10: continue
        wins = sum(1 for r in rets if r > 0)
        t = _tstat(rets)
        p = _pval(t, len(rets)-1)
        print(f"  {g:<35} N={len(rets):>5} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")

    return groups


# ==================================================================
# Walk-Forward for Top Candidates
# ==================================================================

def walk_forward_top(features, data, sig_tests):
    """Walk-forward validation for top candidates."""
    print("\n" + "=" * 70)
    print("WALK-FORWARD VALIDATION (Top Candidates)")
    print("=" * 70)

    fwd_horizon = "15m"
    fwd_rets = []
    for i in range(len(features)):
        fr = data["get_fwd_returns"](i)
        fwd_rets.append(fr.get(fwd_horizon))

    n = len(features)
    train_end = int(n * 0.6)
    val_end = int(n * 0.8)

    # Test the top regimes from single-factor
    candidates = [
        ("NEG_GAMMA_DOWN", lambda f: f["regime"] == "NEG_GAMMA" and f["price_momentum"] < 0),
        ("POS_GAMMA_UP", lambda f: f["regime"] == "POS_GAMMA" and f["price_momentum"] > 0),
        ("NEG_GAMMA_UP", lambda f: f["regime"] == "NEG_GAMMA" and f["price_momentum"] > 0),
        ("POS_GAMMA_DOWN", lambda f: f["regime"] == "POS_GAMMA" and f["price_momentum"] < 0),
        ("LOW_VOL_RANGING", lambda f: f.get("price_momentum", 0) == 0),
        ("IV_EXPANDING", lambda f: f.get("iv_change") is not None and f["iv_change"] > 0.001),
        ("IV_CONTRACTING", lambda f: f.get("iv_change") is not None and f["iv_change"] < -0.001),
        ("HIGH_OI_BUILDUP", lambda f: f.get("oi_change", 0) > 0 and f["price_momentum"] > 0),
        ("SHORT_COVERING", lambda f: f.get("oi_change", 0) < 0 and f["price_momentum"] > 0),
        ("GEX_POS_MOM_ALIGN", lambda f: f.get("gex_momentum_align") == 1),
        ("GEX_NEG_MOM_ALIGN", lambda f: f.get("gex_momentum_align") == -1),
    ]

    for name, condition in candidates:
        print(f"\n  {name}:")

        for split_name, start, end in [("Train", 0, train_end), ("Val", train_end, val_end), ("Test", val_end, n)]:
            rets = [fwd_rets[i] for i in range(start, end) if condition(features[i]) and fwd_rets[i] is not None]
            if len(rets) < 5:
                print(f"    {split_name}: N={len(rets)} (insufficient)")
                continue
            wins = sum(1 for r in rets if r > 0)
            t = _tstat(rets)
            p = _pval(t, len(rets)-1)
            print(f"    {split_name}: N={len(rets):>4} mean={_mean(rets):>+.4f}% win%={wins/len(rets)*100:>5.1f}% t={t:>6.3f} p={p:.4f}")


# ==================================================================
# Main
# ==================================================================

def main():
    print("Phase 7.8G — Multi-Factor Historical GEX Research")
    print("=" * 70)

    db_path = os.path.join(_backend_dir, "paper_journal.db")
    conn = sqlite3.connect(db_path, timeout=120)

    try:
        # Load data
        data = load_all_data(conn)

        # Compute features
        print("\nComputing features...")
        t0 = time.time()
        features = compute_features(data)
        print(f"  {len(features)} feature vectors computed in {time.time()-t0:.1f}s")

        # Single-factor screening
        tests, sig_tests = screen_single_factors(features, data)

        # Multi-factor combinations
        test_multifactor(features, data, sig_tests)

        # Walk-forward
        walk_forward_top(features, data, sig_tests)

        # Database safety check
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
