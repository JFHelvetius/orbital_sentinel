"""Tests del N-to-N pairwise screening v0.3 (ADR-0018)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.conjunctions import (
    EARTH_GRAVITATIONAL_PARAMETER_KM3_S2,
    MAX_PAIRS_DEFAULT,
    SCREENING_ENGINE_VERSION,
    SCREENING_SCHEMA_VERSION,
    ScreeningResult,
    analyze_pairwise_screening,
)
from orbital_sentinel.analytics.conjunctions.screening import (
    _apogee_perigee_km,
    _possible_conjunction,
)
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _make_snapshot_from_fixture(name: str) -> TLESnapshot:
    text = (FIXTURES / name).read_text(encoding="ascii")
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset=name.replace(".txt", ""),
        url=f"https://example/{name}",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


def _iss_element_and_snapshot():
    snap = _make_snapshot_from_fixture("iss_vallado_2008.txt")
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return element, snap


def _multi_elements_and_snapshot():
    snap = _make_snapshot_from_fixture("multi_stations.txt")
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return elements, snap


# --- Helpers de apogeo/perigeo -------------------------------------------


def test_apogee_perigee_iss_in_leo_range() -> None:
    """ISS: a ≈ 6780 km, e ≈ 0.0007 → perigee ≈ apogee ≈ 6780 km."""
    element, _ = _iss_element_and_snapshot()
    perigee, apogee = _apogee_perigee_km(element)
    # ISS rango altitud: ~400 km → distancia del centro: ~6780 km
    assert 6700 < perigee < 6850
    assert 6700 < apogee < 6850
    assert apogee >= perigee  # invariante


def test_apogee_perigee_synthetic_geo() -> None:
    """NORAD 99999 sintético: mean_motion=1.0 → a ≈ GEO."""
    elements, _ = _multi_elements_and_snapshot()
    _, geo = elements  # NORAD 99999
    perigee, apogee = _apogee_perigee_km(geo)
    # Para mean_motion=1.0 rev/día (período 24h), a ≈ 42 250 km
    assert 42000 < perigee < 42500
    assert 42000 < apogee < 42500


def test_possible_conjunction_overlapping_ranges() -> None:
    element, _ = _iss_element_and_snapshot()
    assert _possible_conjunction(element, element, threshold_km=1.0)


def test_possible_conjunction_leo_vs_geo_returns_false() -> None:
    elements, _ = _multi_elements_and_snapshot()
    iss, geo = elements
    assert _possible_conjunction(iss, geo, threshold_km=1000.0) is False


def test_possible_conjunction_threshold_can_bridge_gap() -> None:
    """Con threshold suficientemente grande, hasta LEO+GEO 'pueden' conjuntar."""
    elements, _ = _multi_elements_and_snapshot()
    iss, geo = elements
    # Diferencia LEO-GEO ≈ 35 000 km
    assert _possible_conjunction(iss, geo, threshold_km=40000.0) is True


# --- Casos triviales -----------------------------------------------------


def test_empty_list_yields_trivial_result() -> None:
    result = analyze_pairwise_screening(
        [],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=5.0, threshold_km=10.0,
    )
    assert result.n_objects == 0
    assert result.n_pairs_total == 0
    assert result.n_pairs_screened == 0
    assert result.n_detections == 0
    assert result.detections == []


def test_single_object_yields_no_pairs() -> None:
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=5.0, threshold_km=10.0,
    )
    assert result.n_objects == 1
    assert result.n_pairs_total == 0


# --- Filtro apogeo/perigeo en acción -------------------------------------


def test_iss_vs_geo_filtered_out_by_apogee_perigee() -> None:
    elements, snap = _multi_elements_and_snapshot()
    iss, geo = elements
    result = analyze_pairwise_screening(
        [(iss, snap), (geo, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0, threshold_km=1000.0,
    )
    assert result.n_pairs_total == 1
    assert result.n_pairs_filtered_out == 1
    assert result.n_pairs_screened == 0
    assert result.n_detections == 0


def test_filter_disabled_analyzes_all_pairs() -> None:
    elements, snap = _multi_elements_and_snapshot()
    iss, geo = elements
    result = analyze_pairwise_screening(
        [(iss, snap), (geo, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=2),
        step_minutes=10.0, threshold_km=1000.0,
        apogee_perigee_filter=False,
    )
    assert result.n_pairs_filtered_out == 0
    assert result.n_pairs_screened == 1
    # ISS vs GEO sigue siendo > 30 000 km de miss → no detección
    assert result.n_detections == 0


# --- Mismo objeto duplicado en la lista produce detección ----------------


def test_same_object_duplicated_produces_detection() -> None:
    """Lista [ISS, ISS] → 1 par superviviente del filtro, miss ≈ 0."""
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap), (element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, threshold_km=1.0,
    )
    assert result.n_pairs_total == 1
    assert result.n_pairs_filtered_out == 0
    assert result.n_pairs_screened == 1
    assert result.n_detections == 1
    assert result.detections[0].miss_distance_km == pytest.approx(0.0, abs=1e-9)


# --- Threshold ----------------------------------------------------------


def test_threshold_zero_rejected() -> None:
    element, snap = _iss_element_and_snapshot()
    with pytest.raises(ValueError, match="threshold_km"):
        analyze_pairwise_screening(
            [(element, snap)],
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
            step_minutes=5.0, threshold_km=0.0,
        )


def test_threshold_negative_rejected() -> None:
    element, snap = _iss_element_and_snapshot()
    with pytest.raises(ValueError, match="threshold_km"):
        analyze_pairwise_screening(
            [(element, snap)],
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
            step_minutes=5.0, threshold_km=-1.0,
        )


# --- Cap max_pairs ------------------------------------------------------


def test_max_pairs_exceeded_raises() -> None:
    """max_pairs=0 con dos objetos (1 par) → excede el cap."""
    elements, snap = _multi_elements_and_snapshot()
    iss, geo = elements
    with pytest.raises(ValueError, match="max_pairs"):
        analyze_pairwise_screening(
            [(iss, snap), (geo, snap)],
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
            step_minutes=10.0, threshold_km=1000.0,
            max_pairs=0,
        )


# --- Provenance preservada en detecciones --------------------------------


def test_detections_carry_provenance_chains() -> None:
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap), (element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, threshold_km=1.0,
    )
    detection = result.detections[0]
    assert detection.element_a_content_hash_source == element.content_hash_source
    assert detection.element_b_content_hash_source == element.content_hash_source


# --- Versiones ----------------------------------------------------------


def test_screening_versions_are_0_1_0() -> None:
    assert SCREENING_SCHEMA_VERSION == "0.1.0"
    assert SCREENING_ENGINE_VERSION == "0.1.0"


def test_screening_default_max_pairs_5000() -> None:
    assert MAX_PAIRS_DEFAULT == 5000


def test_earth_gm_value() -> None:
    """Constante WGS84 estándar."""
    assert EARTH_GRAVITATIONAL_PARAMETER_KM3_S2 == 398600.4418


# --- Modelo Pydantic frozen ---------------------------------------------


def test_screening_result_is_frozen() -> None:
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=5.0, threshold_km=10.0,
    )
    with pytest.raises(Exception):
        result.n_detections = 99  # type: ignore[misc]


def test_screening_result_rejects_extra_fields() -> None:
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
        step_minutes=5.0, threshold_km=10.0,
    )
    with pytest.raises(Exception):
        ScreeningResult.model_validate({**result.model_dump(), "extra": 0})


# --- Detecciones ordenadas por miss ASC ---------------------------------


def test_detections_sorted_by_miss_distance_ascending() -> None:
    """Lista [ISS, ISS, ISS] → tres pares duplicados con miss ≈ 0; ordenados."""
    element, snap = _iss_element_and_snapshot()
    result = analyze_pairwise_screening(
        [(element, snap), (element, snap), (element, snap)],
        window_start=EPOCH, window_end=EPOCH + timedelta(minutes=10),
        step_minutes=2.0, threshold_km=1.0,
    )
    assert result.n_pairs_total == 3
    assert result.n_detections == 3
    misses = [d.miss_distance_km for d in result.detections]
    assert misses == sorted(misses)
