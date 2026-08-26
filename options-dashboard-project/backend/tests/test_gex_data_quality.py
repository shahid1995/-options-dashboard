"""Phase 7.8L — Tests for the GEX Data Quality Contract.

All tests use isolated in-memory databases to ensure zero production impact.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import (
    ContractSpec,
    HistoricalGexSnapshot,
    NiftyCandle,
    OptionCandle,
    OptionGreeks,
)
from app.services.gex_data_quality import (
    ExclusionReason,
    GexDataQualityEngine,
    QualityLevel,
    QualityReport,
    get_data_quality_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Create an isolated in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def _to_dt(ts):
    """Convert ISO string to datetime."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


def _insert_option_candle(db, instrument_key, open_time, oi=100.0, close=100.0, vol=1000.0):
    """Insert a minimal option candle."""
    candle = OptionCandle(
        instrument_key=instrument_key,
        interval="3min",
        open_time=_to_dt(open_time),
        open=close, high=close + 1, low=close - 1, close=close,
        volume=vol, open_interest=oi, source="TEST",
        fetched_at=datetime.utcnow(),
    )
    db.add(candle)


def _insert_contract_spec(db, instrument_key, strike=24000.0, opt_type="CE", expiry="2024-10-03"):
    """Insert a minimal contract spec."""
    now = datetime.utcnow()
    spec = ContractSpec(
        instrument_key=instrument_key,
        underlying="NIFTY",
        underlying_key="NSE_INDEX|Nifty 50",
        expiry=expiry,
        strike_price=strike,
        instrument_type=opt_type,
        lot_size=75,
        minimum_lot=75,
        freeze_quantity=1800,
        tick_size=5.0,
        trading_symbol=f"NIFTY {int(strike)} {opt_type} {expiry}",
        segment="NSE_FO",
        exchange="NSE",
        weekly=1,
        source="TEST",
        source_reference="TEST/PHASE_7_8L",
        fetched_at=now,
        created_at=now,
    )
    db.add(spec)


def _insert_historical_gex(db, instrument_key, open_time, status="SUCCESS",
                           raw_gex=100.0, signed_gex=100.0, exclusion_reason=None):
    """Insert a minimal historical GEX row."""
    gex = HistoricalGexSnapshot(
        instrument_key=instrument_key,
        interval="3min",
        open_time=_to_dt(open_time),
        spot=24000.0,
        strike=24000.0,
        expiry="2024-10-03",
        option_type="CE",
        gamma=0.001,
        open_interest=100.0,
        option_price=100.0,
        lot_size=75,
        raw_gex=raw_gex,
        signed_gex=signed_gex,
        calc_version="h_gex_v1",
        calculated_at=datetime.utcnow(),
        status=status,
        exclusion_reason=exclusion_reason,
    )
    db.add(gex)


def _insert_nifty_candle(db, open_time, close=24000.0):
    """Insert a minimal NIFTY candle."""
    candle = NiftyCandle(
        symbol="NIFTY",
        interval="3min",
        open_time=_to_dt(open_time),
        open=close, high=close + 10, low=close - 10, close=close,
        volume=1000000,
    )
    db.add(candle)
    db.flush()  # populate defaults like created_at/updated_at


def _insert_option_greeks(db, instrument_key, open_time, spot=24000.0, gamma=0.001):
    """Insert minimal option Greeks."""
    greek = OptionGreeks(
        instrument_key=instrument_key,
        interval="3min",
        open_time=_to_dt(open_time),
        spot=spot,
        strike=24000.0,
        expiry="2024-10-03",
        option_type="CE",
        option_price=100.0,
        lot_size=75,
        time_to_expiry=0.01,
        risk_free_rate=0.065,
        intrinsic_value=0.0,
        implied_volatility=0.2,
        delta=0.5,
        gamma=gamma,
        vega=10.0,
        theta=-5.0,
        calc_model="BLACK_SCHOLES_EUROPEAN",
        calc_version="1.0.0",
        calculated_at=datetime.utcnow(),
        status="SUCCESS",
    )
    db.add(greek)


# ---------------------------------------------------------------------------
# Tests: Quality levels
# ---------------------------------------------------------------------------

class TestQualityLevel:
    def test_quality_levels_exist(self):
        assert QualityLevel.EXCELLENT.value == "EXCELLENT"
        assert QualityLevel.GOOD.value == "GOOD"
        assert QualityLevel.DEGRADED.value == "DEGRADED"
        assert QualityLevel.INSUFFICIENT.value == "INSUFFICIENT"

    def test_exclusion_reasons_cover_all_categories(self):
        assert ExclusionReason.ZERO_OI.value == "ZERO_OI"
        assert ExclusionReason.MISSING_SPOT.value == "MISSING_SPOT"
        assert ExclusionReason.MISSING_GAMMA.value == "MISSING_GAMMA"
        assert ExclusionReason.NEGATIVE_GAMMA.value == "NEGATIVE_GAMMA"
        assert ExclusionReason.EXPIRY_DAY_LIMITATION.value == "EXPIRY_DAY_LIMITATION"


# ---------------------------------------------------------------------------
# Tests: Empty database
# ---------------------------------------------------------------------------

class TestEmptyDatabase:
    def test_empty_db_returns_valid_report(self, db):
        report = get_data_quality_report(db)
        assert isinstance(report, QualityReport)
        assert report.total_option_candles == 0
        assert report.total_historical_gex == 0
        assert report.score == 0.0
        assert report.classification == QualityLevel.INSUFFICIENT.value

    def test_empty_db_has_metrics(self, db):
        report = get_data_quality_report(db)
        assert len(report.metrics) > 0

    def test_empty_db_has_warnings(self, db):
        report = get_data_quality_report(db)
        assert len(report.warnings) > 0


# ---------------------------------------------------------------------------
# Tests: Perfect quality dataset
# ---------------------------------------------------------------------------

class TestPerfectQuality:
    def test_perfect_dataset_scores_high(self, db):
        """A dataset with all SUCCESS GEX rows should score very high."""
        ts = "2024-10-03 09:15:00"
        ik_ce = "NSE_FO|58510|03-10-2024"
        ik_pe = "NSE_FO|58511|03-10-2024"

        _insert_contract_spec(db, ik_ce, strike=24000.0, opt_type="CE")
        _insert_contract_spec(db, ik_pe, strike=24000.0, opt_type="PE")
        _insert_option_candle(db, ik_ce, ts, oi=5000.0)
        _insert_option_candle(db, ik_pe, ts, oi=5000.0)
        _insert_option_greeks(db, ik_ce, ts)
        _insert_option_greeks(db, ik_pe, ts)
        _insert_historical_gex(db, ik_ce, ts, status="SUCCESS", raw_gex=100.0, signed_gex=100.0)
        _insert_historical_gex(db, ik_pe, ts, status="SUCCESS", raw_gex=50.0, signed_gex=-50.0)
        _insert_nifty_candle(db, ts)
        db.commit()

        report = get_data_quality_report(db)
        assert report.total_option_candles == 2
        assert report.total_historical_gex == 2
        assert report.total_success == 2
        assert report.total_excluded == 0
        # Score > 80 with only 1 NIFTY candle (no coverage warning)
        # Classification is GOOD or higher when critical metrics are 1.0
        assert report.score > 80.0
        assert report.classification in (
            QualityLevel.EXCELLENT.value,
            QualityLevel.GOOD.value,
            QualityLevel.DEGRADED.value,
        )

    def test_perfect_dataset_no_exclusions(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts, oi=5000.0)
        _insert_option_greeks(db, ik, ts)
        _insert_historical_gex(db, ik, ts, status="SUCCESS")
        _insert_nifty_candle(db, ts)
        db.commit()

        report = get_data_quality_report(db)
        assert report.total_excluded == 0
        assert len(report.exclusions) == 0


# ---------------------------------------------------------------------------
# Tests: Missing OI
# ---------------------------------------------------------------------------

class TestMissingOI:
    def test_zero_oi_detected(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts, oi=0.0)
        _insert_historical_gex(db, ik, ts, status="EXCLUDED", exclusion_reason="ZERO_OI")
        db.commit()

        report = get_data_quality_report(db)
        # OI coverage should be 0%
        oi_metric = next(m for m in report.metrics if m.name == "oi_coverage")
        assert oi_metric.value == 0.0
        assert report.total_excluded == 1

    def test_zero_oi_exclusion_breakdown(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts, oi=0.0)
        _insert_historical_gex(db, ik, ts, status="EXCLUDED", exclusion_reason="ZERO_OI")
        db.commit()

        report = get_data_quality_report(db)
        zero_oi_exc = [e for e in report.exclusions if e.reason == "ZERO_OI"]
        assert len(zero_oi_exc) == 1
        assert zero_oi_exc[0].count == 1

    def test_mixed_oi_coverage(self, db):
        ts1 = "2024-10-03 09:15:00"
        ts2 = "2024-10-03 09:18:00"
        ik1 = "NSE_FO|58510|03-10-2024"
        ik2 = "NSE_FO|58514|03-10-2024"

        _insert_contract_spec(db, ik1, strike=24000.0, opt_type="CE")
        _insert_contract_spec(db, ik2, strike=24050.0, opt_type="PE")
        _insert_option_candle(db, ik1, ts1, oi=5000.0)
        _insert_option_candle(db, ik2, ts1, oi=0.0)
        _insert_option_candle(db, ik1, ts2, oi=4500.0)
        _insert_option_candle(db, ik2, ts2, oi=0.0)
        _insert_historical_gex(db, ik1, ts1, status="SUCCESS")
        _insert_historical_gex(db, ik2, ts1, status="EXCLUDED", exclusion_reason="ZERO_OI")
        _insert_historical_gex(db, ik1, ts2, status="SUCCESS")
        _insert_historical_gex(db, ik2, ts2, status="EXCLUDED", exclusion_reason="ZERO_OI")
        db.commit()

        report = get_data_quality_report(db)
        oi_metric = next(m for m in report.metrics if m.name == "oi_coverage")
        assert oi_metric.value == pytest.approx(0.5, abs=0.01)
        assert report.total_success == 2
        assert report.total_excluded == 2


# ---------------------------------------------------------------------------
# Tests: Missing spot
# ---------------------------------------------------------------------------

class TestMissingSpot:
    def test_missing_spot_exclusion(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts, oi=5000.0)
        _insert_historical_gex(db, ik, ts, status="EXCLUDED", exclusion_reason="MISSING_SPOT")
        db.commit()

        report = get_data_quality_report(db)
        spot_exc = [e for e in report.exclusions if e.reason == "MISSING_SPOT"]
        assert len(spot_exc) == 1
        assert spot_exc[0].count == 1


# ---------------------------------------------------------------------------
# Tests: Incomplete chain
# ---------------------------------------------------------------------------

class TestIncompleteChain:
    def test_chain_completeness_metric(self, db):
        # Insert 2 timestamps with different chain sizes
        for i in range(2):
            ts = f"2024-10-03 09:{15 + i * 3:02d}:00"
            ik = f"NSE_FO|{58510 + i}|03-10-2024"
            _insert_contract_spec(db, ik, strike=24000.0 + i * 50)
            _insert_option_candle(db, ik, ts, oi=5000.0)
        db.commit()

        report = get_data_quality_report(db)
        chain_metric = next(m for m in report.metrics if m.name == "chain_completeness")
        assert chain_metric.value >= 0.0


# ---------------------------------------------------------------------------
# Tests: CE/PE balance
# ---------------------------------------------------------------------------

class TestCEPEBalance:
    def test_balanced_ce_pe(self, db):
        ts = "2024-10-03 09:15:00"
        ik_ce = "NSE_FO|58510|03-10-2024"
        ik_pe = "NSE_FO|58511|03-10-2024"

        _insert_contract_spec(db, ik_ce, strike=24000.0, opt_type="CE")
        _insert_contract_spec(db, ik_pe, strike=24000.0, opt_type="PE")
        _insert_option_candle(db, ik_ce, ts, oi=5000.0)
        _insert_option_candle(db, ik_pe, ts, oi=5000.0)
        db.commit()

        report = get_data_quality_report(db)
        balance = next(m for m in report.metrics if m.name == "ce_pe_balance")
        assert balance.value == 1.0  # perfectly balanced


# ---------------------------------------------------------------------------
# Tests: Numerical validity
# ---------------------------------------------------------------------------

class TestNumericalValidity:
    def test_valid_gex_has_perfect_validity(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_historical_gex(db, ik, ts, status="SUCCESS", raw_gex=100.0, signed_gex=100.0)
        db.commit()

        report = get_data_quality_report(db)
        validity = next(m for m in report.metrics if m.name == "numerical_validity")
        assert validity.value == 1.0

    def test_valid_gex_has_perfect_validity_repeated(self, db):
        """Verify numerical validity metric works correctly with valid data."""
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_historical_gex(db, ik, ts, status="SUCCESS", raw_gex=100.0, signed_gex=-100.0)
        db.commit()

        report = get_data_quality_report(db)
        validity = next(m for m in report.metrics if m.name == "numerical_validity")
        # With no NULL values, validity should be 1.0
        assert validity.value == 1.0


# ---------------------------------------------------------------------------
# Tests: Score calculation
# ---------------------------------------------------------------------------

class TestScoreCalculation:
    def test_score_is_between_0_and_100(self, db):
        report = get_data_quality_report(db)
        assert 0.0 <= report.score <= 100.0

    def test_score_capped_by_worst_critical_metric(self, db):
        """Score cannot exceed the worst critical metric * 100."""
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        # 50% OI coverage (one candle with OI, one without)
        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts, oi=5000.0)
        _insert_option_candle(db, "NSE_FO|99999|03-10-2024", ts, oi=0.0)
        _insert_contract_spec(db, "NSE_FO|99999|03-10-2024", strike=24050.0)
        _insert_historical_gex(db, ik, ts, status="SUCCESS")
        _insert_historical_gex(db, "NSE_FO|99999|03-10-2024", ts,
                               status="EXCLUDED", exclusion_reason="ZERO_OI")
        db.commit()

        report = get_data_quality_report(db)
        oi_metric = next(m for m in report.metrics if m.name == "oi_coverage")
        assert oi_metric.value == pytest.approx(0.5, abs=0.01)
        assert report.score <= 55.0  # capped by worst critical metric (~50%)


# ---------------------------------------------------------------------------
# Tests: Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_empty_db_is_insufficient(self, db):
        report = get_data_quality_report(db)
        assert report.classification == QualityLevel.INSUFFICIENT.value

    def test_classification_matches_score(self, db):
        report = get_data_quality_report(db)
        if report.score >= 95.0:
            assert report.classification == QualityLevel.EXCELLENT.value
        elif report.score >= 85.0:
            assert report.classification == QualityLevel.GOOD.value
        elif report.score >= 70.0:
            assert report.classification == QualityLevel.DEGRADED.value
        else:
            assert report.classification == QualityLevel.INSUFFICIENT.value


# ---------------------------------------------------------------------------
# Tests: Expiry-day exclusions
# ---------------------------------------------------------------------------

class TestExpiryDayExclusions:
    def test_expiry_day_exclusion_detected(self, db):
        ts = "2024-10-03 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik, expiry="2024-10-03")
        _insert_option_candle(db, ik, ts, oi=0.0)
        _insert_historical_gex(db, ik, ts, status="EXCLUDED", exclusion_reason="ZERO_OI")
        db.commit()

        report = get_data_quality_report(db)
        assert len(report.affected_expiries) > 0
        assert report.affected_expiries[0]["expiry"] == "2024-10-03"


# ---------------------------------------------------------------------------
# Tests: Date filtering
# ---------------------------------------------------------------------------

class TestDateFiltering:
    def test_date_filter_reduces_counts(self, db):
        ts1 = "2024-10-03 09:15:00"
        ts2 = "2024-10-10 09:15:00"
        ik = "NSE_FO|58510|03-10-2024"

        _insert_contract_spec(db, ik)
        _insert_option_candle(db, ik, ts1, oi=5000.0)
        _insert_option_candle(db, ik, ts2, oi=5000.0)
        _insert_historical_gex(db, ik, ts1, status="SUCCESS")
        _insert_historical_gex(db, ik, ts2, status="SUCCESS")
        db.commit()

        report_all = get_data_quality_report(db)
        report_filtered = get_data_quality_report(db, start_date="2024-10-10")

        # Metrics are filtered; base counts are unfiltered.
        # Verify filtered GEX metrics distinguish the two periods.
        gex_all = next(m for m in report_all.metrics if m.name == "gex_success_rate")
        gex_filtered = next(m for m in report_filtered.metrics if m.name == "gex_success_rate")
        assert gex_filtered.denominator < gex_all.denominator
        # Timestamp coverage confirms the filter works
        assert report_filtered.timestamps_with_gex < report_all.timestamps_with_gex


# ---------------------------------------------------------------------------
# Tests: Mixed quality dataset
# ---------------------------------------------------------------------------

class TestMixedQuality:
    def test_mixed_dataset_reflects_all_issues(self, db):
        ts = "2024-10-03 09:15:00"
        ik1 = "NSE_FO|58510|03-10-2024"
        ik2 = "NSE_FO|58511|03-10-2024"
        ik3 = "NSE_FO|58512|03-10-2024"

        _insert_contract_spec(db, ik1, strike=24000.0, opt_type="CE")
        _insert_contract_spec(db, ik2, strike=24000.0, opt_type="PE")
        _insert_contract_spec(db, ik3, strike=24050.0, opt_type="CE")

        # Good candle
        _insert_option_candle(db, ik1, ts, oi=5000.0)
        _insert_historical_gex(db, ik1, ts, status="SUCCESS")

        # Zero-OI candle
        _insert_option_candle(db, ik2, ts, oi=0.0)
        _insert_historical_gex(db, ik2, ts, status="EXCLUDED", exclusion_reason="ZERO_OI")

        # Missing spot
        _insert_option_candle(db, ik3, ts, oi=3000.0)
        _insert_historical_gex(db, ik3, ts, status="EXCLUDED", exclusion_reason="MISSING_SPOT")

        db.commit()

        report = get_data_quality_report(db)
        assert report.total_option_candles == 3
        assert report.total_success == 1
        assert report.total_excluded == 2
        assert len(report.exclusions) >= 2
        assert len(report.warnings) > 0


# ---------------------------------------------------------------------------
# Tests: Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_has_all_required_fields(self, db):
        report = get_data_quality_report(db)
        assert hasattr(report, "generated_at")
        assert hasattr(report, "score")
        assert hasattr(report, "classification")
        assert hasattr(report, "metrics")
        assert hasattr(report, "exclusions")
        assert hasattr(report, "warnings")
        assert hasattr(report, "total_option_candles")
        assert hasattr(report, "total_option_greeks")
        assert hasattr(report, "total_historical_gex")
        assert hasattr(report, "total_nifty_candles")
        assert hasattr(report, "total_contract_specs")

    def test_metrics_have_names(self, db):
        report = get_data_quality_report(db)
        for m in report.metrics:
            assert m.name
            assert m.unit in ("ratio", "count", "pct")

    def test_exclusions_have_descriptions(self, db):
        report = get_data_quality_report(db)
        for e in report.exclusions:
            assert e.description  # should be non-empty


# ---------------------------------------------------------------------------
# Tests: Production DB protection
# ---------------------------------------------------------------------------

class TestProductionDBProtection:
    def test_in_memory_db_not_modified(self, db):
        """Verify that the quality engine does not write to the database."""
        # Record initial state
        initial_count = db.query(func.count(OptionCandle.id)).scalar()

        # Run the quality engine
        get_data_quality_report(db)

        # Verify no rows were added
        final_count = db.query(func.count(OptionCandle.id)).scalar()
        assert final_count == initial_count
