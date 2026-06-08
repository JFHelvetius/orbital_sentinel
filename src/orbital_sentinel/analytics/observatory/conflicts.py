"""Detección de pases simultáneos (ADR-0025)."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

OVERLAP_DEFINITION_NAME = "any_overlap_v1"


class PassConflict(BaseModel):
    """Solapamiento temporal de dos pases de NORAD distintos."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    norad_a: int
    norad_b: int
    overlap_start: AwareDatetime
    overlap_end: AwareDatetime
    overlap_seconds: float = Field(ge=0.0)
    overlap_definition: str = Field(default=OVERLAP_DEFINITION_NAME)


def detect_pass_conflicts(
    scan: object,  # ObservatoryScan
    *,
    overlap_threshold_seconds: float = 0.0,
) -> list[PassConflict]:
    """Devuelve la lista de conflictos (pares de pases solapados).

    Orden estable: ascendente por (overlap_start, norad_a, norad_b).
    """
    from orbital_sentinel.analytics.observatory.scan import ObservatoryScan

    if not isinstance(scan, ObservatoryScan):
        raise TypeError("scan debe ser una ObservatoryScan")
    if overlap_threshold_seconds < 0:
        raise ValueError("overlap_threshold_seconds debe ser >= 0")

    flat: list[tuple[int, AwareDatetime, AwareDatetime]] = []
    for sat in scan.satellites:
        for p in sat.passes:
            flat.append((sat.norad_cat_id, p.aos_time, p.los_time))

    conflicts: list[PassConflict] = []
    for i in range(len(flat)):
        norad_i, aos_i, los_i = flat[i]
        for j in range(i + 1, len(flat)):
            norad_j, aos_j, los_j = flat[j]
            if norad_i == norad_j:
                continue
            overlap_start = max(aos_i, aos_j)
            overlap_end = min(los_i, los_j)
            overlap = (overlap_end - overlap_start).total_seconds()
            if overlap > overlap_threshold_seconds:
                # canonicalizar ordenar por norad ascendente
                na, nb = (norad_i, norad_j) if norad_i < norad_j else (norad_j, norad_i)
                conflicts.append(
                    PassConflict(
                        norad_a=na,
                        norad_b=nb,
                        overlap_start=overlap_start,
                        overlap_end=overlap_end,
                        overlap_seconds=overlap,
                    )
                )

    conflicts.sort(key=lambda c: (c.overlap_start, c.norad_a, c.norad_b))
    return conflicts
