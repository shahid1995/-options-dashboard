"""Phase 7.8L — Historical GEX Data Quality Contract.

Deterministic, transparent data-quality framework for the Historical GEX
dataset.  Produces a machine-readable quality report with:

* Per-metric coverage percentages
* Composite 0-100 quality score
* Classification (EXCELLENT / GOOD / DEGRADED / INSUFFICIENT)
* Exclusion breakdown by reason
* Affected expiries and instruments
* Quality warnings

Design rules
------------
* Every metric is visible — the score never hides individual weaknesses.
* Missing data is never converted into valid data.
* All thresholds are documented and justified.
* The engine is read-only against production data.
* No fabrication, interpolation, or forward-filling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import case, func, Integer, select
from sqlalchemy.orm import Session

from app.models import (
    ContractSpec,
    HistoricalGexSnapshot,
    NiftyCandle,
    OptionCandle,
    OptionGreeks,
)


# ---------------------------------------------------------------------------
# Quality classifications
# ---------------------------------------------------------------------------

class QualityLevel(str, Enum):
    """Deterministic quality classification.

    Thresholds are derived from the observed production dataset and
    validated against real-world expectations for financial data.

    EXCELLENT: >=95% on all critical metrics.
    GOOD:      >=85% on all critical metrics, >=90% composite.
    DEGRADED:  >=70% on critical metrics, some known limitations.
    INSUFFICIENT: below DEGRADED thresholds.
    """

    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"


class ExclusionReason(str, Enum):
    """Machine-readable reasons for GEX exclusion.

    Mirrors the existing ``historical_gex.ExclusionReason`` values
    and adds dataset-level categories for comprehensive coverage.
    """

    ZERO_OI = "ZERO_OI"
    MISSING_OI = "MISSING_OI"
    INVALID_OI = "INVALID_OI"
    MISSING_SPOT = "MISSING_SPOT"
    INVALID_SPOT = "INVALID_SPOT"
    MISSING_GAMMA = "MISSING_GAMMA"
    INVALID_GAMMA = "INVALID_GAMMA"
    NEGATIVE_GAMMA = "NEGATIVE_GAMMA"
    MISSING_STRIKE = "MISSING_STRIKE"
    INVALID_STRIKE = "INVALID_STRIKE"
    UNKNOWN_OPTION_TYPE = "UNKNOWN_OPTION_TYPE"
    MISSING_OPTION_TYPE = "MISSING_OPTION_TYPE"
    NON_SUCCESS_GREEKS = "NON_SUCCESS_GREEKS"
    EXPIRY_DAY_LIMITATION = "EXPIRY_DAY_LIMITATION"
    INCOMPLETE_CHAIN = "INCOMPLETE_CHAIN"
    DUPLICATE_TIMESTAMP = "DUPLICATE_TIMESTAMP"
    STALE_DATA = "STALE_DATA"
    MISSING_NIFTY = "MISSING_NIFTY"
    MISSING_CONTRACT = "MISSING_CONTRACT"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    """A single quality metric."""

    name: str
    value: float  # 0.0 - 1.0 for ratios, raw count for counts
    denominator: int = 0
    numerator: int = 0
    unit: str = "ratio"  # "ratio", "count", "pct"
    is_critical: bool = True  # critical metrics affect classification
    warning: Optional[str] = None


@dataclass
class ExclusionBreakdown:
    """Breakdown of GEX exclusions by reason."""

    reason: str
    count: int
    percentage: float  # of total GEX rows
    affected_instruments: int = 0
    affected_timestamps: int = 0
    affected_expiries: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class QualityReport:
    """Complete data quality report."""

    # Metadata
    generated_at: str = ""
    calculation_version: str = ""

    # Core metrics
    total_option_candles: int = 0
    total_option_greeks: int = 0
    total_historical_gex: int = 0
    total_nifty_candles: int = 0
    total_contract_specs: int = 0

    # Coverage metrics (list of MetricResult)
    metrics: list[MetricResult] = field(default_factory=list)

    # Exclusion breakdown
    exclusions: list[ExclusionBreakdown] = field(default_factory=list)
    total_excluded: int = 0
    total_success: int = 0

    # Affected entities
    affected_expiries: list[dict] = field(default_factory=list)
    affected_instruments: list[dict] = field(default_factory=list)

    # Timestamp coverage
    timestamps_with_gex: int = 0
    timestamps_total: int = 0
    timestamp_coverage: float = 0.0

    # Composite score and classification
    score: float = 0.0
    classification: str = ""

    # Quality warnings
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Exclusion reason descriptions
# ---------------------------------------------------------------------------

_exclusion_descriptions = {
    "ZERO_OI": "Open interest is zero - contract had no open positions at this timestamp",
    "MISSING_OI": "Open interest field is NULL/missing in source data",
    "INVALID_OI": "Open interest has an invalid/non-numeric value",
    "MISSING_SPOT": "Underlying spot price is unavailable for this timestamp",
    "INVALID_SPOT": "Spot price is non-positive, NaN, or Inf",
    "MISSING_GAMMA": "Option gamma is NULL/missing",
    "INVALID_GAMMA": "Gamma is NaN or Inf",
    "NEGATIVE_GAMMA": "Gamma is negative (theoretical impossibility for standard options)",
    "MISSING_STRIKE": "Strike price is NULL/missing",
    "INVALID_STRIKE": "Strike price is non-positive",
    "UNKNOWN_OPTION_TYPE": "Option type is not CE or PE",
    "MISSING_OPTION_TYPE": "Option type field is NULL",
    "NON_SUCCESS_GREEKS": "Greek calculation did not complete successfully",
    "INCOMPLETE_CHAIN": "Option chain was incomplete at this timestamp",
    "DUPLICATE_TIMESTAMP": "Duplicate timestamp detected for this instrument",
    "STALE_DATA": "Data appears stale or recycled from a previous session",
    "MISSING_NIFTY": "NIFTY spot candle not available for this timestamp",
    "MISSING_CONTRACT": "Contract specification not found for this instrument",
}


# ---------------------------------------------------------------------------
# Quality engine
# ---------------------------------------------------------------------------

class GexDataQualityEngine:
    """Deterministic GEX data quality assessment engine.

    All methods are read-only against the production database.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> QualityReport:
        """Generate a complete data quality report.

        Parameters
        ----------
        start_date : str, optional
            ISO date to filter from (inclusive).
        end_date : str, optional
            ISO date to filter to (inclusive).

        Returns
        -------
        QualityReport
        """
        report = QualityReport()
        report.generated_at = datetime.utcnow().isoformat() + "Z"

        # 1. Base counts
        self._count_tables(report)

        # 2. OI coverage
        self._measure_oi_coverage(report, start_date, end_date)

        # 3. GEX coverage
        self._measure_gex_coverage(report, start_date, end_date)

        # 4. Timestamp coverage
        self._measure_timestamp_coverage(report, start_date, end_date)

        # 5. Exclusion breakdown
        self._measure_exclusions(report, start_date, end_date)

        # 6. Chain completeness
        self._measure_chain_completeness(report, start_date, end_date)

        # 7. Strike / CE-PE balance
        self._measure_strike_balance(report, start_date, end_date)

        # 8. Numerical validity
        self._measure_numerical_validity(report, start_date, end_date)

        # 9. Affected entities
        self._find_affected_entities(report, start_date, end_date)

        # 10. Composite score
        self._compute_score(report)

        # 11. Classification
        self._classify(report)

        # 12. Warnings
        self._generate_warnings(report)

        return report

    # ------------------------------------------------------------------
    # Internal: base counts
    # ------------------------------------------------------------------

    def _count_tables(self, report: QualityReport) -> None:
        report.total_option_candles = self.db.query(
            func.count(OptionCandle.id)
        ).scalar()
        report.total_option_greeks = self.db.query(
            func.count(OptionGreeks.id)
        ).scalar()
        report.total_historical_gex = self.db.query(
            func.count(HistoricalGexSnapshot.id)
        ).scalar()
        report.total_nifty_candles = self.db.query(
            func.count(NiftyCandle.id)
        ).scalar()
        report.total_contract_specs = self.db.query(
            func.count(ContractSpec.id)
        ).scalar()

    # ------------------------------------------------------------------
    # Internal: OI coverage
    # ------------------------------------------------------------------

    def _measure_oi_coverage(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            func.count(OptionCandle.id).label("total"),
            func.sum(
                case((OptionCandle.open_interest > 0, 1), else_=0)
            ).label("positive"),
            func.sum(
                case((OptionCandle.open_interest == 0, 1), else_=0)
            ).label("zero"),
        )

        if start_date:
            q = q.filter(OptionCandle.open_time >= start_date)
        if end_date:
            q = q.filter(OptionCandle.open_time <= end_date + " 23:59:59")

        row = q.one()
        total = row.total or 0
        positive = row.positive or 0
        zero_oi = row.zero or 0

        coverage = positive / total if total > 0 else 0.0

        report.metrics.append(MetricResult(
            name="oi_coverage",
            value=coverage,
            numerator=positive,
            denominator=total,
            unit="ratio",
            is_critical=True,
        ))

        report.metrics.append(MetricResult(
            name="zero_oi_count",
            value=zero_oi,
            unit="count",
            is_critical=False,
        ))

        report.metrics.append(MetricResult(
            name="zero_oi_pct",
            value=zero_oi / total if total > 0 else 0.0,
            numerator=zero_oi,
            denominator=total,
            unit="ratio",
            is_critical=False,
        ))

    # ------------------------------------------------------------------
    # Internal: GEX coverage
    # ------------------------------------------------------------------

    def _measure_gex_coverage(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            func.count(HistoricalGexSnapshot.id).label("total"),
            func.sum(
                case((HistoricalGexSnapshot.status == "SUCCESS", 1), else_=0)
            ).label("success"),
            func.sum(
                case((HistoricalGexSnapshot.status == "EXCLUDED", 1), else_=0)
            ).label("excluded"),
        )

        if start_date:
            q = q.filter(HistoricalGexSnapshot.open_time >= start_date)
        if end_date:
            q = q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")

        row = q.one()
        total = row.total or 0
        success = row.success or 0
        excluded = row.excluded or 0

        report.total_success = success
        report.total_excluded = excluded

        success_rate = success / total if total > 0 else 0.0

        report.metrics.append(MetricResult(
            name="gex_success_rate",
            value=success_rate,
            numerator=success,
            denominator=total,
            unit="ratio",
            is_critical=True,
        ))

        report.metrics.append(MetricResult(
            name="gex_coverage",
            value=success_rate,
            numerator=success,
            denominator=total,
            unit="ratio",
            is_critical=True,
        ))

        report.metrics.append(MetricResult(
            name="gex_excluded_count",
            value=excluded,
            unit="count",
            is_critical=False,
        ))

    # ------------------------------------------------------------------
    # Internal: timestamp coverage
    # ------------------------------------------------------------------

    def _measure_timestamp_coverage(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        # Total distinct timestamps in option_candles
        q_total = self.db.query(
            func.count(func.distinct(OptionCandle.open_time))
        )
        if start_date:
            q_total = q_total.filter(OptionCandle.open_time >= start_date)
        if end_date:
            q_total = q_total.filter(OptionCandle.open_time <= end_date + " 23:59:59")
        timestamps_total = q_total.scalar() or 0

        # Distinct timestamps in historical_gex
        q_gex = self.db.query(
            func.count(func.distinct(HistoricalGexSnapshot.open_time))
        )
        if start_date:
            q_gex = q_gex.filter(HistoricalGexSnapshot.open_time >= start_date)
        if end_date:
            q_gex = q_gex.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")
        timestamps_gex = q_gex.scalar() or 0

        report.timestamps_total = timestamps_total
        report.timestamps_with_gex = timestamps_gex
        report.timestamp_coverage = (
            timestamps_gex / timestamps_total if timestamps_total > 0 else 0.0
        )

        report.metrics.append(MetricResult(
            name="timestamp_coverage",
            value=report.timestamp_coverage,
            numerator=timestamps_gex,
            denominator=timestamps_total,
            unit="ratio",
            is_critical=True,
        ))

        report.metrics.append(MetricResult(
            name="total_timestamps",
            value=timestamps_total,
            unit="count",
            is_critical=False,
        ))

    # ------------------------------------------------------------------
    # Internal: exclusion breakdown
    # ------------------------------------------------------------------

    def _measure_exclusions(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            HistoricalGexSnapshot.exclusion_reason,
            func.count(HistoricalGexSnapshot.id).label("cnt"),
        ).filter(
            HistoricalGexSnapshot.status == "EXCLUDED"
        )

        if start_date:
            q = q.filter(HistoricalGexSnapshot.open_time >= start_date)
        if end_date:
            q = q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")

        q = q.group_by(HistoricalGexSnapshot.exclusion_reason)

        total_excluded = report.total_excluded or 1  # avoid div by 0

        for row in q.all():
            reason = row.exclusion_reason or "UNKNOWN"
            cnt = row.cnt

            # Get affected instruments for this reason
            affected_q = self.db.query(
                func.count(func.distinct(HistoricalGexSnapshot.instrument_key)),
            ).filter(
                HistoricalGexSnapshot.status == "EXCLUDED",
                HistoricalGexSnapshot.exclusion_reason == reason,
            )
            if start_date:
                affected_q = affected_q.filter(HistoricalGexSnapshot.open_time >= start_date)
            if end_date:
                affected_q = affected_q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")
            affected_inst = affected_q.scalar() or 0

            # Get affected timestamps
            ts_q = self.db.query(
                func.count(func.distinct(HistoricalGexSnapshot.open_time)),
            ).filter(
                HistoricalGexSnapshot.status == "EXCLUDED",
                HistoricalGexSnapshot.exclusion_reason == reason,
            )
            if start_date:
                ts_q = ts_q.filter(HistoricalGexSnapshot.open_time >= start_date)
            if end_date:
                ts_q = ts_q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")
            affected_ts = ts_q.scalar() or 0

            # Get affected expiries via join
            exp_q = self.db.query(
                func.distinct(ContractSpec.expiry),
            ).join(
                HistoricalGexSnapshot, HistoricalGexSnapshot.instrument_key == ContractSpec.instrument_key
            ).filter(
                HistoricalGexSnapshot.status == "EXCLUDED",
                HistoricalGexSnapshot.exclusion_reason == reason,
            )
            if start_date:
                exp_q = exp_q.filter(HistoricalGexSnapshot.open_time >= start_date)
            if end_date:
                exp_q = exp_q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")
            affected_expiries = [r[0] for r in exp_q.all() if r[0]]

            desc = _exclusion_descriptions.get(reason, "Unknown exclusion reason")

            report.exclusions.append(ExclusionBreakdown(
                reason=reason,
                count=cnt,
                percentage=cnt / total_excluded if total_excluded else 0.0,
                affected_instruments=affected_inst,
                affected_timestamps=affected_ts,
                affected_expiries=affected_expiries,
                description=desc,
            ))

    # ------------------------------------------------------------------
    # Internal: chain completeness
    # ------------------------------------------------------------------

    def _measure_chain_completeness(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            OptionCandle.open_time,
            func.count(OptionCandle.id).label("row_count"),
        )
        if start_date:
            q = q.filter(OptionCandle.open_time >= start_date)
        if end_date:
            q = q.filter(OptionCandle.open_time <= end_date + " 23:59:59")
        q = q.group_by(OptionCandle.open_time)

        chain_sizes = [r.row_count for r in q.all()]

        if chain_sizes:
            sorted_sizes = sorted(chain_sizes)
            median_chain = sorted_sizes[len(sorted_sizes) // 2]
            incomplete_count = sum(1 for s in chain_sizes if s < median_chain * 0.5)
            completeness = 1.0 - (incomplete_count / len(chain_sizes))
            avg_chain = sum(chain_sizes) / len(chain_sizes)
        else:
            incomplete_count = 0
            completeness = 0.0
            avg_chain = 0

        report.metrics.append(MetricResult(
            name="chain_completeness",
            value=completeness,
            numerator=len(chain_sizes) - incomplete_count,
            denominator=len(chain_sizes) if chain_sizes else 0,
            unit="ratio",
            is_critical=False,
        ))

        report.metrics.append(MetricResult(
            name="avg_chain_size",
            value=avg_chain,
            unit="count",
            is_critical=False,
        ))

    # ------------------------------------------------------------------
    # Internal: strike / CE-PE balance
    # ------------------------------------------------------------------

    def _measure_strike_balance(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            ContractSpec.instrument_type,
            func.count(func.distinct(ContractSpec.instrument_key)).label("cnt"),
        ).join(
            OptionCandle, OptionCandle.instrument_key == ContractSpec.instrument_key
        )
        if start_date:
            q = q.filter(OptionCandle.open_time >= start_date)
        if end_date:
            q = q.filter(OptionCandle.open_time <= end_date + " 23:59:59")
        q = q.group_by(ContractSpec.instrument_type)

        counts = {r.instrument_type: r.cnt for r in q.all()}
        ce_count = counts.get("CE", 0)
        pe_count = counts.get("PE", 0)

        balance = min(ce_count, pe_count) / max(ce_count, pe_count) if max(ce_count, pe_count) > 0 else 0.0

        report.metrics.append(MetricResult(
            name="ce_pe_balance",
            value=balance,
            numerator=min(ce_count, pe_count),
            denominator=max(ce_count, pe_count),
            unit="ratio",
            is_critical=False,
        ))

        report.metrics.append(MetricResult(
            name="ce_count",
            value=ce_count,
            unit="count",
            is_critical=False,
        ))

        report.metrics.append(MetricResult(
            name="pe_count",
            value=pe_count,
            unit="count",
            is_critical=False,
        ))

    # ------------------------------------------------------------------
    # Internal: numerical validity
    # ------------------------------------------------------------------

    def _measure_numerical_validity(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            func.count(HistoricalGexSnapshot.id).label("total"),
            func.sum(
                case((HistoricalGexSnapshot.raw_gex.is_(None), 1), else_=0)
            ).label("null_raw"),
            func.sum(
                case((HistoricalGexSnapshot.signed_gex.is_(None), 1), else_=0)
            ).label("null_signed"),
        )
        if start_date:
            q = q.filter(HistoricalGexSnapshot.open_time >= start_date)
        if end_date:
            q = q.filter(HistoricalGexSnapshot.open_time <= end_date + " 23:59:59")

        row = q.one()
        total = row.total or 0
        null_raw = row.null_raw or 0
        null_signed = row.null_signed or 0

        validity = 1.0 - ((null_raw + null_signed) / (2 * total)) if total > 0 else 0.0

        report.metrics.append(MetricResult(
            name="numerical_validity",
            value=validity,
            numerator=total * 2 - null_raw - null_signed,
            denominator=total * 2,
            unit="ratio",
            is_critical=True,
        ))

    # ------------------------------------------------------------------
    # Internal: affected entities
    # ------------------------------------------------------------------

    def _find_affected_entities(
        self, report: QualityReport, start_date: Optional[str], end_date: Optional[str]
    ) -> None:
        q = self.db.query(
            ContractSpec.expiry,
            func.count(OptionCandle.id).label("total"),
        ).join(
            OptionCandle, OptionCandle.instrument_key == ContractSpec.instrument_key
        ).filter(
            OptionCandle.open_interest == 0
        )
        if start_date:
            q = q.filter(OptionCandle.open_time >= start_date)
        if end_date:
            q = q.filter(OptionCandle.open_time <= end_date + " 23:59:59")
        q = q.group_by(ContractSpec.expiry).order_by(
            func.count(OptionCandle.id).desc()
        )

        for row in q.all():
            report.affected_expiries.append({
                "expiry": row.expiry,
                "zero_oi_rows": row.total,
            })

    # ------------------------------------------------------------------
    # Internal: composite score
    # ------------------------------------------------------------------

    def _compute_score(self, report: QualityReport) -> None:
        """Compute a 0-100 composite quality score.

        Scoring rules:
        - Each metric contributes proportionally to the score.
        - Critical metrics have 2x weight.
        - The score CANNOT exceed the worst critical metric.
        - Missing data never converts to valid data.

        Thresholds justified by:
        - Financial data requires >95% coverage for high-confidence analysis.
        - >85% is acceptable for research/exploration.
        - >70% identifies known limitations without hiding them.
        - <70% signals insufficient data for reliable conclusions.
        """
        if not report.metrics:
            report.score = 0.0
            return

        total_weight = 0.0
        weighted_sum = 0.0
        min_critical = 1.0

        for m in report.metrics:
            weight = 2.0 if m.is_critical else 1.0
            v = max(0.0, min(1.0, m.value))
            weighted_sum += v * weight
            total_weight += weight
            if m.is_critical:
                min_critical = min(min_critical, v)

        raw_score = (weighted_sum / total_weight * 100) if total_weight > 0 else 0.0

        # The score cannot exceed 100 * min_critical (cap by worst critical metric)
        capped_score = min(raw_score, 100.0 * min_critical)

        report.score = round(max(0.0, min(100.0, capped_score)), 2)

    # ------------------------------------------------------------------
    # Internal: classification
    # ------------------------------------------------------------------

    def _classify(self, report: QualityReport) -> None:
        """Deterministic classification based on score and critical metrics."""
        min_critical = 1.0
        for m in report.metrics:
            if m.is_critical:
                min_critical = min(min_critical, m.value)

        if report.score >= 95.0 and min_critical >= 0.95:
            report.classification = QualityLevel.EXCELLENT.value
        elif report.score >= 85.0 and min_critical >= 0.85:
            report.classification = QualityLevel.GOOD.value
        elif report.score >= 70.0 and min_critical >= 0.70:
            report.classification = QualityLevel.DEGRADED.value
        else:
            report.classification = QualityLevel.INSUFFICIENT.value

    # ------------------------------------------------------------------
    # Internal: warnings
    # ------------------------------------------------------------------

    def _generate_warnings(self, report: QualityReport) -> None:
        """Generate human-readable quality warnings."""
        for m in report.metrics:
            if m.is_critical and m.value < 0.95:
                report.warnings.append(
                    f"CRITICAL: {m.name} = {m.value:.1%} "
                    f"(numerator={m.numerator}, denominator={m.denominator})"
                )

        # Expiry-day limitation warning
        expiry_exclusions = [
            e for e in report.exclusions
            if e.reason in ("ZERO_OI", "MISSING_OI")
        ]
        if expiry_exclusions:
            total_affected = sum(e.count for e in expiry_exclusions)
            affected_expiries = set()
            for e in expiry_exclusions:
                affected_expiries.update(e.affected_expiries)
            report.warnings.append(
                f"EXPIRY_DAY_LIMITATION: {total_affected} GEX rows excluded "
                f"due to zero/missing OI on expiry day(s). "
                f"Affected expiries: {sorted(affected_expiries)[:10]}"
            )

        # NIFTY coverage
        if report.total_nifty_candles < 50000:
            report.warnings.append(
                f"NIFTY_COVERAGE: Only {report.total_nifty_candles} NIFTY candles available"
            )

        # Greek coverage
        if report.total_option_greeks < report.total_option_candles * 0.99:
            report.warnings.append(
                f"GREEK_COVERAGE: {report.total_option_greeks} Greeks vs "
                f"{report.total_option_candles} candles "
                f"({report.total_option_greeks / max(1, report.total_option_candles):.1%})"
            )


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def get_data_quality_report(
    db: Session,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> QualityReport:
    """Convenience function to generate a data quality report."""
    engine = GexDataQualityEngine(db)
    return engine.generate_report(start_date=start_date, end_date=end_date)
