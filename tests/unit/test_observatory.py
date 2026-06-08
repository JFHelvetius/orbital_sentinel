"""Tests de observatory scan / ranking / conflicts (ADR-0025)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orbital_sentinel.analytics.observatory import (
    OBSERVATORY_SCAN_ENGINE_VERSION,
    OBSERVATORY_SCAN_SCHEMA_VERSION,
    OVERLAP_DEFINITION_NAME,
    ObservatoryScan,
    PassConflict,
    RankingCriterion,
    SatellitePasses,
    UsefulPassFilter,
    detect_pass_conflicts,
    is_geometrically_unreachable,
    rank_passes,
    scan_observatory,
)
from orbital_sentinel.analytics.passes import Pass
from orbital_sentinel.analytics.solar import TwilightPhase
from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
EPOCH = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)
DERIVED_AT_FIXED = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
CDMX_LAT, CDMX_LON, CDMX_ALT = 19.4326, -99.1332, 2240.0


def _iss_setup() -> tuple[object, TLESnapshot]:
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    encoded = text.encode("ascii")
    snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://example/",
        fetched_at=DERIVED_AT_FIXED,
        raw_text=text,
        n_bytes=len(encoded),
    )
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT_FIXED)
    return element, snap


def _fixed_clock() -> datetime:
    return DERIVED_AT_FIXED


# --- Pre-filtro geométrico ---------------------------------------------


def test_is_geometrically_unreachable_iss_visible_from_cdmx() -> None:
    """ISS (i=51.6°) es visible desde CDMX (lat=19°)."""
    element, _ = _iss_setup()
    assert is_geometrically_unreachable(element, CDMX_LAT) is False


def test_is_geometrically_unreachable_iss_not_visible_from_high_lat() -> None:
    """ISS no visible desde lat 89° (más allá de i + half_cone + margin)."""
    element, _ = _iss_setup()
    assert is_geometrically_unreachable(element, 89.0) is True


# --- scan_observatory --------------------------------------------------


def test_scan_observatory_with_one_satellite_emits_provenance() -> None:
    element, snap = _iss_setup()
    scan = scan_observatory(
        [(element, snap)],
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=8),
        step_minutes=0.5, min_elevation_deg=10.0,
        useful_pass_filter=UsefulPassFilter(
            require_observer_in_twilight_or_darker=False,
            require_satellite_illuminated=False,
        ),
        clock=_fixed_clock,
    )
    assert scan.n_satellites_input == 1
    assert scan.n_satellites_scanned == 1
    assert scan.n_satellites_skipped_geometric == 0
    assert len(scan.satellites) == 1
    sp = scan.satellites[0]
    assert sp.norad_cat_id == element.norad_cat_id
    assert sp.element_content_hash_source == element.content_hash_source
    assert sp.element_tle_content_hash == element.tle_content_hash


def test_scan_observatory_versioning_and_honesty_fields() -> None:
    element, snap = _iss_setup()
    scan = scan_observatory(
        [(element, snap)],
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=4),
        step_minutes=1.0,
        clock=_fixed_clock,
    )
    assert scan.schema_version == OBSERVATORY_SCAN_SCHEMA_VERSION == "0.1.0"
    assert scan.engine_version == OBSERVATORY_SCAN_ENGINE_VERSION == "0.1.0"
    assert scan.useful_pass_filter is not None
    assert scan.frame_model == "spherical_earth_geocentric_topocentric_v1"
    assert scan.solar_position_model == "vallado_2008_low_precision_v1"
    assert scan.shadow_model == "cylindrical_earth_shadow_v1"


def test_scan_observatory_pre_filter_skips_unreachable_sats() -> None:
    """Observador a 89°N → ISS marcado como geometric_unreachable, sin propagar."""
    element, snap = _iss_setup()
    scan = scan_observatory(
        [(element, snap)],
        observer_lat_deg=89.0, observer_lon_deg=0.0, observer_alt_m=0.0,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=8),
        step_minutes=1.0,
        clock=_fixed_clock,
    )
    assert scan.n_satellites_skipped_geometric == 1
    assert scan.n_satellites_scanned == 0
    assert scan.satellites == []


def test_scan_observatory_respects_max_satellites_cap() -> None:
    element, snap = _iss_setup()
    with pytest.raises(ValueError, match="max_satellites"):
        scan_observatory(
            [(element, snap)] * 10,
            observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
            window_start=EPOCH, window_end=EPOCH + timedelta(hours=1),
            step_minutes=1.0,
            max_satellites=5,
        )


def test_scan_observatory_determinism() -> None:
    element, snap = _iss_setup()
    kwargs = dict(
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=4),
        step_minutes=0.5, min_elevation_deg=10.0,
        useful_pass_filter=UsefulPassFilter(
            require_observer_in_twilight_or_darker=False,
            require_satellite_illuminated=False,
        ),
        clock=_fixed_clock,
    )
    a = scan_observatory([(element, snap)], **kwargs)
    b = scan_observatory([(element, snap)], **kwargs)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


def test_scan_useful_pass_filter_reduces_count() -> None:
    """Sin filtro (todo útil) vs con filtro estricto → menor número útil."""
    element, snap = _iss_setup()
    no_filter = UsefulPassFilter(
        require_observer_in_twilight_or_darker=False,
        require_satellite_illuminated=False,
    )
    strict = UsefulPassFilter(
        require_observer_in_twilight_or_darker=True,
        minimum_twilight_phase=TwilightPhase.ASTRONOMICAL,
        require_satellite_illuminated=True,
    )
    common = dict(
        observer_lat_deg=CDMX_LAT, observer_lon_deg=CDMX_LON, observer_alt_m=CDMX_ALT,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=0.5, min_elevation_deg=10.0,
        clock=_fixed_clock,
    )
    s_no = scan_observatory([(element, snap)], useful_pass_filter=no_filter, **common)
    s_strict = scan_observatory([(element, snap)], useful_pass_filter=strict, **common)
    # n_useful_passes_total con filtro estricto ≤ sin filtro
    assert s_strict.n_useful_passes_total <= s_no.n_useful_passes_total


# --- ranking ----------------------------------------------------------


def _synthetic_pass(
    aos: datetime, los: datetime, max_elev: float, azimuth: float = 90.0
) -> Pass:
    """Construye un Pass sintético con timestamps + max_elevation."""
    return Pass(
        aos_time=aos,
        culmination_time=aos + (los - aos) / 2,
        los_time=los,
        aos_was_refined=True,
        los_was_refined=True,
        partial_aos=False,
        partial_los=False,
        duration_seconds=(los - aos).total_seconds(),
        max_elevation_deg=max_elev,
        aos_azimuth_deg=azimuth,
        culmination_azimuth_deg=azimuth,
        los_azimuth_deg=azimuth,
    )


def _scan_with(passes_per_norad: dict[int, list[Pass]]) -> ObservatoryScan:
    """Construye un ObservatoryScan sintético con pases por NORAD."""
    sats = [
        SatellitePasses(
            norad_cat_id=n,
            object_name=f"SAT-{n}",
            element_content_hash_source="a" * 64,
            element_tle_index=0,
            element_tle_content_hash="b" * 64,
            passes=ps,
            n_passes=len(ps),
            n_useful_passes=len(ps),
        )
        for n, ps in passes_per_norad.items()
    ]
    return ObservatoryScan(
        observer_lat_deg=0.0, observer_lon_deg=0.0, observer_alt_m=0.0,
        window_start=EPOCH, window_end=EPOCH + timedelta(hours=24),
        step_minutes=1.0, min_elevation_deg=0.0,
        n_satellites_input=len(sats),
        n_satellites_skipped_geometric=0,
        n_satellites_scanned=len(sats),
        n_passes_total=sum(len(ps) for ps in passes_per_norad.values()),
        n_useful_passes_total=sum(len(ps) for ps in passes_per_norad.values()),
        satellites=sats,
        useful_pass_filter=UsefulPassFilter(),
        derived_at=DERIVED_AT_FIXED,
    )


def test_rank_passes_by_max_elevation_desc() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=5), max_elev=30.0)],
        2: [_synthetic_pass(t0, t0 + timedelta(minutes=5), max_elev=80.0)],
        3: [_synthetic_pass(t0, t0 + timedelta(minutes=5), max_elev=50.0)],
    })
    ranked = rank_passes(scan, criterion=RankingCriterion.MAX_ELEVATION)
    assert [r.norad_cat_id for r in ranked] == [2, 3, 1]
    assert [r.rank for r in ranked] == [1, 2, 3]
    assert ranked[0].criterion_value == 80.0


def test_rank_passes_by_duration() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=4), max_elev=10.0)],
        2: [_synthetic_pass(t0, t0 + timedelta(minutes=8), max_elev=10.0)],
    })
    ranked = rank_passes(scan, criterion=RankingCriterion.DURATION)
    assert ranked[0].norad_cat_id == 2
    assert ranked[1].norad_cat_id == 1


def test_rank_passes_by_earliest() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0 + timedelta(hours=2), t0 + timedelta(hours=2, minutes=5), 30.0)],
        2: [_synthetic_pass(t0, t0 + timedelta(minutes=5), 30.0)],
    })
    ranked = rank_passes(scan, criterion=RankingCriterion.EARLIEST)
    assert ranked[0].norad_cat_id == 2


def test_rank_passes_limit() -> None:
    t0 = EPOCH
    scan = _scan_with({
        i: [_synthetic_pass(t0, t0 + timedelta(minutes=5), max_elev=float(i))]
        for i in range(1, 6)
    })
    ranked = rank_passes(scan, criterion=RankingCriterion.MAX_ELEVATION, limit=2)
    assert len(ranked) == 2
    assert ranked[0].criterion_value == 5.0


def test_rank_passes_empty_scan() -> None:
    scan = _scan_with({})
    ranked = rank_passes(scan, criterion=RankingCriterion.MAX_ELEVATION)
    assert ranked == []


# --- conflicts --------------------------------------------------------


def test_detect_conflicts_finds_overlap() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=10), 30.0)],
        2: [_synthetic_pass(t0 + timedelta(minutes=5), t0 + timedelta(minutes=15), 40.0)],
    })
    conflicts = detect_pass_conflicts(scan)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c.norad_a, c.norad_b) == (1, 2)
    assert c.overlap_seconds == pytest.approx(300.0, abs=1e-6)
    assert c.overlap_definition == OVERLAP_DEFINITION_NAME


def test_detect_conflicts_no_overlap() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=5), 30.0)],
        2: [_synthetic_pass(t0 + timedelta(hours=1), t0 + timedelta(hours=1, minutes=5), 30.0)],
    })
    conflicts = detect_pass_conflicts(scan)
    assert conflicts == []


def test_detect_conflicts_same_norad_excluded() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [
            _synthetic_pass(t0, t0 + timedelta(minutes=10), 30.0),
            _synthetic_pass(t0 + timedelta(minutes=5), t0 + timedelta(minutes=15), 40.0),
        ],
    })
    conflicts = detect_pass_conflicts(scan)
    assert conflicts == []


def test_detect_conflicts_threshold_filters() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=10), 30.0)],
        2: [_synthetic_pass(t0 + timedelta(minutes=9), t0 + timedelta(minutes=15), 40.0)],
    })
    # Threshold 120s → solo se reporta si overlap > 120s. Aquí overlap=60s.
    conflicts = detect_pass_conflicts(scan, overlap_threshold_seconds=120.0)
    assert conflicts == []
    # Threshold 30s → se reporta.
    conflicts = detect_pass_conflicts(scan, overlap_threshold_seconds=30.0)
    assert len(conflicts) == 1


def test_pass_conflict_extra_forbid() -> None:
    t0 = EPOCH
    scan = _scan_with({
        1: [_synthetic_pass(t0, t0 + timedelta(minutes=10), 30.0)],
        2: [_synthetic_pass(t0 + timedelta(minutes=5), t0 + timedelta(minutes=15), 40.0)],
    })
    c = detect_pass_conflicts(scan)[0]
    with pytest.raises(Exception):
        PassConflict.model_validate({**c.model_dump(mode="json"), "extra": 1})
