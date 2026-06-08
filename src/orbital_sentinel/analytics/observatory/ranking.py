"""Ranking de pases por criterio declarado (ADR-0025)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orbital_sentinel.analytics.passes import Pass

RANKING_CRITERIA_VERSION = "0.1.0"


class RankingCriterion(StrEnum):
    """Criterios de ranking declarados (ADR-0025)."""

    MAX_ELEVATION = "max_elevation"
    DURATION = "duration"
    EARLIEST = "earliest"
    LATEST = "latest"


class RankedPass(BaseModel):
    """Un pase rankeado con su NORAD y valor del criterio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1)
    norad_cat_id: int
    criterion: RankingCriterion
    criterion_value: float
    pass_: Pass = Field(alias="pass")


def _criterion_value(p: Pass, criterion: RankingCriterion) -> float:
    if criterion == RankingCriterion.MAX_ELEVATION:
        return p.max_elevation_deg
    if criterion == RankingCriterion.DURATION:
        return p.duration_seconds
    if criterion == RankingCriterion.EARLIEST:
        # Menor timestamp = mejor → invertimos signo para que sort desc sea natural
        return -p.aos_time.timestamp()
    if criterion == RankingCriterion.LATEST:
        return p.aos_time.timestamp()
    raise ValueError(f"RankingCriterion no reconocido: {criterion}")  # pragma: no cover


def rank_passes(
    scan: object,  # ObservatoryScan; tipo evitado por import circular
    *,
    criterion: RankingCriterion,
    limit: int | None = None,
) -> list[RankedPass]:
    """Devuelve los pases del ``scan`` ordenados por ``criterion`` descendente.

    Orden estable: ties se resuelven por ``norad_cat_id`` ascendente.
    """
    # Lazy import para evitar ciclo en el momento de definición.
    from orbital_sentinel.analytics.observatory.scan import ObservatoryScan

    if not isinstance(scan, ObservatoryScan):
        raise TypeError("scan debe ser una ObservatoryScan")

    candidates: list[tuple[int, Pass, float]] = []
    for sat in scan.satellites:
        for p in sat.passes:
            candidates.append((sat.norad_cat_id, p, _criterion_value(p, criterion)))

    # Sort descendente por criterio, desempate ascendente por NORAD y AOS.
    candidates.sort(key=lambda t: (-t[2], t[0], t[1].aos_time))

    if limit is not None:
        candidates = candidates[:limit]

    result: list[RankedPass] = []
    for idx, (norad, p, value) in enumerate(candidates, start=1):
        # Para EARLIEST devolvemos el valor original (no negado) en criterion_value
        reported_value = -value if criterion == RankingCriterion.EARLIEST else value
        result.append(
            RankedPass.model_validate(
                {
                    "rank": idx,
                    "norad_cat_id": norad,
                    "criterion": criterion,
                    "criterion_value": reported_value,
                    "pass": p,
                }
            )
        )
    return result
