"""Historical GEX Analytics API — Phase 7.8D.

Endpoints:
  GET /gex/history          — time-series GEX aggregation
  GET /gex/regime           — gamma regime history
  GET /gex/flip             — gamma flip detection
  GET /gex/walls            — gamma wall detection
  GET /gex/analytics        — combined price+GEX relationship
  GET /gex/stats            — statistical analysis by regime/group

All endpoints require session authentication. Read-only. No database writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.deps import get_current_user, AuthenticatedUser
from app.services.historical_gex_analytics import GexAnalyticsEngine

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TimestampGexOut(BaseModel):
    timestamp: str
    spot: float
    callGex: float
    putGex: float
    netGex: float
    absoluteGex: float
    instrumentCount: int
    strikeCount: int


class GexChangeOut(BaseModel):
    timestamp: str
    currentNetGex: float
    previousNetGex: Optional[float] = None
    gexChange: Optional[float] = None
    gexChangePct: Optional[float] = None


class GexAccelerationOut(BaseModel):
    timestamp: str
    currentChange: Optional[float] = None
    previousChange: Optional[float] = None
    acceleration: Optional[float] = None


class GammaRegimeOut(BaseModel):
    timestamp: str
    spot: float
    netGex: float
    regime: str
    previousRegime: Optional[str] = None
    regimeTransition: Optional[str] = None
    regimeDuration: int = 0


class GammaFlipOut(BaseModel):
    timestamp: str
    spot: float
    flipStrike: Optional[float] = None
    flipConfidence: Optional[float] = None
    numSignChanges: int = 0
    status: str


class GammaWallOut(BaseModel):
    strike: float
    gex: float
    absoluteGex: float
    distanceFromSpot: float
    distancePct: float
    wallType: str
    rank: int


class GammaWallsResultOut(BaseModel):
    timestamp: str
    spot: float
    strongestPositive: Optional[GammaWallOut] = None
    strongestNegative: Optional[GammaWallOut] = None
    positiveWalls: list[GammaWallOut] = Field(default_factory=list)
    negativeWalls: list[GammaWallOut] = Field(default_factory=list)


class PriceGexPointOut(BaseModel):
    timestamp: str
    spot: float
    netGex: float
    gexChange: Optional[float] = None
    gexAcceleration: Optional[float] = None
    gammaRegime: Optional[str] = None
    gammaFlip: Optional[float] = None
    strongestPositiveWall: Optional[float] = None
    strongestNegativeWall: Optional[float] = None
    spotReturn3m: Optional[float] = None
    spotReturn6m: Optional[float] = None
    spotReturn9m: Optional[float] = None
    spotReturn15m: Optional[float] = None
    spotReturn30m: Optional[float] = None
    spotReturn60m: Optional[float] = None
    maxFavorable: Optional[float] = None
    maxAdverse: Optional[float] = None


class StatsOut(BaseModel):
    count: int
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    winPct: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    maxFavorable: Optional[float] = None
    maxAdverse: Optional[float] = None


class HistoryResponse(BaseModel):
    timestamps: list[TimestampGexOut]
    changes: list[GexChangeOut]
    accelerations: list[GexAccelerationOut]
    count: int


class RegimeResponse(BaseModel):
    regimes: list[GammaRegimeOut]
    count: int


class FlipResponse(BaseModel):
    flips: list[GammaFlipOut]
    count: int


class WallsResponse(BaseModel):
    walls: list[GammaWallsResultOut]
    count: int


class AnalyticsResponse(BaseModel):
    series: list[PriceGexPointOut]
    count: int


class StatsResponse(BaseModel):
    byRegime: dict = Field(default_factory=dict)
    byGexChange: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/history", response_model=HistoryResponse)
def get_history(
    start: Optional[str] = Query(None, description="Start timestamp (ISO 8601)"),
    end: Optional[str] = Query(None, description="End timestamp (ISO 8601)"),
    limit: int = Query(500, ge=1, le=5000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get historical GEX time-series with change and acceleration."""
    engine = GexAnalyticsEngine(db)
    timestamps = engine.get_timestamps(_parse_dt(start), _parse_dt(end))[:limit]

    aggs = engine.aggregate_timestamps_bulk(timestamps)

    changes = []
    accelerations = []
    for i, ts in enumerate(aggs):
        prev = aggs[i - 1] if i > 0 else None
        ch = engine.compute_gex_change(ts, prev)
        changes.append(ch)
        prev_ch = changes[i - 1] if i > 0 else None
        acc = engine.compute_gex_acceleration(ch, prev_ch)
        accelerations.append(acc)

    return HistoryResponse(
        timestamps=[
            TimestampGexOut(
                timestamp=a.timestamp.isoformat(),
                spot=a.spot,
                callGex=a.call_gex,
                putGex=a.put_gex,
                netGex=a.net_gex,
                absoluteGex=a.absolute_gex,
                instrumentCount=a.instrument_count,
                strikeCount=a.strike_count,
            )
            for a in aggs
        ],
        changes=[
            GexChangeOut(
                timestamp=c.timestamp.isoformat(),
                currentNetGex=c.current_net_gex,
                previousNetGex=c.previous_net_gex,
                gexChange=c.gex_change,
                gexChangePct=c.gex_change_pct,
            )
            for c in changes
        ],
        accelerations=[
            GexAccelerationOut(
                timestamp=a.timestamp.isoformat(),
                currentChange=a.current_change,
                previousChange=a.previous_change,
                acceleration=a.acceleration,
            )
            for a in accelerations
        ],
        count=len(aggs),
    )


@router.get("/regime", response_model=RegimeResponse)
def get_regime(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get gamma regime history."""
    engine = GexAnalyticsEngine(db)
    timestamps = engine.get_timestamps(_parse_dt(start), _parse_dt(end))[:limit]
    aggs = engine.aggregate_timestamps_bulk(timestamps)
    regimes = engine.compute_regime_series(aggs)

    return RegimeResponse(
        regimes=[
            GammaRegimeOut(
                timestamp=r.timestamp.isoformat(),
                spot=r.spot,
                netGex=r.net_gex,
                regime=r.regime,
                previousRegime=r.previous_regime,
                regimeTransition=r.regime_transition,
                regimeDuration=r.regime_duration,
            )
            for r in regimes
        ],
        count=len(regimes),
    )


@router.get("/flip", response_model=FlipResponse)
def get_flip(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get gamma flip detection history."""
    engine = GexAnalyticsEngine(db)
    timestamps = engine.get_timestamps(_parse_dt(start), _parse_dt(end))[:limit]
    flips = [engine.detect_gamma_flip(ts) for ts in timestamps]

    return FlipResponse(
        flips=[
            GammaFlipOut(
                timestamp=f.timestamp.isoformat(),
                spot=f.spot,
                flipStrike=f.flip_strike,
                flipConfidence=f.flip_confidence,
                numSignChanges=f.num_sign_changes,
                status=f.status,
            )
            for f in flips
        ],
        count=len(flips),
    )


@router.get("/walls", response_model=WallsResponse)
def get_walls(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    top_n: int = Query(3, ge=1, le=10),
    limit: int = Query(200, ge=1, le=2000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get gamma wall detection history."""
    engine = GexAnalyticsEngine(db)
    timestamps = engine.get_timestamps(_parse_dt(start), _parse_dt(end))[:limit]

    walls_list = []
    prev = None
    for ts in timestamps:
        w = engine.detect_walls(ts, top_n=top_n, previous_walls=prev)
        walls_list.append(w)
        prev = w

    def wall_to_out(w):
        return GammaWallOut(
            strike=w.strike,
            gex=w.gex,
            absoluteGex=w.absolute_gex,
            distanceFromSpot=w.distance_from_spot,
            distancePct=w.distance_pct,
            wallType=w.wall_type,
            rank=w.rank,
        )

    return WallsResponse(
        walls=[
            GammaWallsResultOut(
                timestamp=w.timestamp.isoformat(),
                spot=w.spot,
                strongestPositive=wall_to_out(w.strongest_positive) if w.strongest_positive else None,
                strongestNegative=wall_to_out(w.strongest_negative) if w.strongest_negative else None,
                positiveWalls=[wall_to_out(pw) for pw in w.positive_walls],
                negativeWalls=[wall_to_out(nw) for nw in w.negative_walls],
            )
            for w in walls_list
        ],
        count=len(walls_list),
    )


@router.get("/analytics", response_model=AnalyticsResponse)
def get_analytics(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get combined price+GEX relationship series with forward returns."""
    engine = GexAnalyticsEngine(db)
    series = engine.build_price_gex_series(_parse_dt(start), _parse_dt(end))

    # Apply limit
    series = series[:limit]

    return AnalyticsResponse(
        series=[
            PriceGexPointOut(
                timestamp=p.timestamp.isoformat(),
                spot=p.spot,
                netGex=p.net_gex,
                gexChange=p.gex_change,
                gexAcceleration=p.gex_acceleration,
                gammaRegime=p.gamma_regime,
                gammaFlip=p.gamma_flip,
                strongestPositiveWall=p.strongest_positive_wall,
                strongestNegativeWall=p.strongest_negative_wall,
                spotReturn3m=p.spot_return_3m,
                spotReturn6m=p.spot_return_6m,
                spotReturn9m=p.spot_return_9m,
                spotReturn15m=p.spot_return_15m,
                spotReturn30m=p.spot_return_30m,
                spotReturn60m=p.spot_return_60m,
                maxFavorable=p.max_favorable,
                maxAdverse=p.max_adverse,
            )
            for p in series
        ],
        count=len(series),
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    forward_return: str = Query("spot_return_15m", description="Forward return field to analyze"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get statistical analysis of forward returns grouped by regime/GEX change."""
    engine = GexAnalyticsEngine(db)
    series = engine.build_price_gex_series(_parse_dt(start), _parse_dt(end))

    by_regime = engine.analyze_by_regime(series, forward_return)
    by_gex_change = engine.analyze_by_gex_change(series, forward_return)

    def stats_to_out(s):
        return StatsOut(
            count=s.count,
            mean=s.mean,
            median=s.median,
            std=s.std,
            winPct=s.win_pct,
            p25=s.p25,
            p75=s.p75,
            maxFavorable=s.max_favorable,
            maxAdverse=s.max_adverse,
        )

    return StatsResponse(
        byRegime={k: stats_to_out(v) for k, v in by_regime.items()},
        byGexChange={k: stats_to_out(v) for k, v in by_gex_change.items()},
    )


# ---------------------------------------------------------------------------
# Phase 7.8E Research Endpoints
# ---------------------------------------------------------------------------

class SignalOut(BaseModel):
    name: str
    entry: str
    direction: str
    regime: str
    sampleSize: int
    winRate: float
    meanReturn: float
    medianReturn: float
    expectedValue: float
    confidence: str


class RobustnessOut(BaseModel):
    robust: bool
    significance: str
    sampleSize: int
    fullSample: dict


class MultipleTestingOut(BaseModel):
    hypothesesTested: int
    apparentlySuccessful: int
    bonferroniAlpha: float
    signals: list


class ResearchResponse(BaseModel):
    datasetSummary: dict
    signals: list[SignalOut]
    robustness: dict
    multipleTesting: MultipleTestingOut
    flipAnalysis: dict
    wallAnalysis: dict
    gexChangeAnalysis: dict
    momentumAnalysis: dict
    regimeAnalysis: dict
    expiryAnalysis: dict
    walkForward: dict
    elapsedSeconds: float


@router.get("/research", response_model=ResearchResponse)
def get_research(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    maxTimestamps: int = Query(500, ge=1, le=12262),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run the Phase 7.8E Historical GEX research pipeline."""
    import time
    from app.services.historical_gex_research import GexResearchEngine

    engine = GexResearchEngine(db)
    t0 = time.time()
    result = engine.run_complete_research(
        start=_parse_dt(start),
        end=_parse_dt(end),
        max_timestamps=maxTimestamps,
    )
    elapsed = time.time() - t0

    return ResearchResponse(
        datasetSummary=result.get("dataset_summary", {}),
        signals=[
            SignalOut(
                name=s["name"],
                entry=s["entry"],
                direction=s["direction"],
                regime=s["regime"],
                sampleSize=s["sample_size"],
                winRate=s["win_rate"],
                meanReturn=s["mean_return"],
                medianReturn=s["median_return"],
                expectedValue=s["expected_value"],
                confidence=s["confidence"],
            )
            for s in result.get("signals", [])
        ],
        robustness=result.get("robustness", {}),
        multipleTesting=MultipleTestingOut(**result.get("multiple_testing", {
            "total_hypotheses_tested": 0,
            "apparently_successful": 0,
            "bonferroni_alpha": 0.05,
            "signals": [],
        })),
        flipAnalysis=result.get("flip_analysis", {}),
        wallAnalysis=result.get("wall_analysis", {}),
        gexChangeAnalysis=result.get("gex_change_analysis", {}),
        momentumAnalysis=result.get("momentum_analysis", {}),
        regimeAnalysis=result.get("regime_analysis", {}),
        expiryAnalysis=result.get("expiry_analysis", {}),
        walkForward=result.get("walk_forward", {}),
        elapsedSeconds=round(elapsed, 2),
    )


# ---------------------------------------------------------------------------
# Data Quality endpoint — Phase 7.8L
# ---------------------------------------------------------------------------


class MetricOut(BaseModel):
    name: str
    value: float
    numerator: int = 0
    denominator: int = 0
    unit: str = "ratio"
    isCritical: bool = True
    warning: Optional[str] = None


class ExclusionOut(BaseModel):
    reason: str
    count: int
    percentage: float
    affectedInstruments: int = 0
    affectedTimestamps: int = 0
    affectedExpiries: list[str] = Field(default_factory=list)
    description: str = ""


class DataQualityOut(BaseModel):
    generatedAt: str
    classification: str
    score: float
    totalOptionCandles: int
    totalOptionGreeks: int
    totalHistoricalGex: int
    totalNiftyCandles: int
    totalContractSpecs: int
    timestampsTotal: int
    timestampsWithGex: int
    timestampCoverage: float
    totalSuccess: int
    totalExcluded: int
    metrics: list[MetricOut]
    exclusions: list[ExclusionOut]
    affectedExpiries: list[dict]
    warnings: list[str]


@router.get("/data-quality", response_model=DataQualityOut)
def gex_data_quality(
    startDate: Optional[str] = Query(None, description="ISO date filter (inclusive)"),
    endDate: Optional[str] = Query(None, description="ISO date filter (inclusive)"),
    user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Data Quality Contract — Phase 7.8L.

    Returns a comprehensive data quality report for the Historical GEX
    dataset including:
    - Overall quality score (0-100)
    - Classification (EXCELLENT / GOOD / DEGRADED / INSUFFICIENT)
    - OI coverage metrics
    - GEX success/exclusion rates
    - Timestamp coverage
    - Exclusion breakdown by reason
    - Affected expiries and instruments
    - Quality warnings
    """
    from app.services.gex_data_quality import get_data_quality_report

    report = get_data_quality_report(db, start_date=startDate, end_date=endDate)

    return DataQualityOut(
        generatedAt=report.generated_at,
        classification=report.classification,
        score=report.score,
        totalOptionCandles=report.total_option_candles,
        totalOptionGreeks=report.total_option_greeks,
        totalHistoricalGex=report.total_historical_gex,
        totalNiftyCandles=report.total_nifty_candles,
        totalContractSpecs=report.total_contract_specs,
        timestampsTotal=report.timestamps_total,
        timestampsWithGex=report.timestamps_with_gex,
        timestampCoverage=round(report.timestamp_coverage, 4),
        totalSuccess=report.total_success,
        totalExcluded=report.total_excluded,
        metrics=[
            MetricOut(
                name=m.name,
                value=round(m.value, 4),
                numerator=m.numerator,
                denominator=m.denominator,
                unit=m.unit,
                isCritical=m.is_critical,
                warning=m.warning,
            )
            for m in report.metrics
        ],
        exclusions=[
            ExclusionOut(
                reason=e.reason,
                count=e.count,
                percentage=round(e.percentage, 4),
                affectedInstruments=e.affected_instruments,
                affectedTimestamps=e.affected_timestamps,
                affectedExpiries=e.affected_expiries,
                description=e.description,
            )
            for e in report.exclusions
        ],
        affectedExpiries=report.affected_expiries,
        warnings=report.warnings,
    )
