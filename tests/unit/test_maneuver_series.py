"""Tests S1–S8 de ``OrbitalElementSeries`` (ADR-0027)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from orbital_sentinel.analytics.maneuvers import OrbitalElementSeries
from orbital_sentinel.catalog.orbital_elements import OrbitalElement

EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
DERIVED_AT = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def make_element(
    *,
    norad: int = 12345,
    days_offset: float = 0.0,
    mean_motion: float = 15.5,
    eccentricity: float = 0.001,
    inclination: float = 51.6,
    tle_hash: str | None = None,
    content_hash_source: str = "a" * 64,
    tle_index: int = 0,
) -> OrbitalElement:
    """Construye un OrbitalElement válido para tests, con campos relevantes
    controlados y el resto con valores razonables."""
    epoch_dt = EPOCH + timedelta(days=days_offset)
    if tle_hash is None:
        seed = f"{norad}-{days_offset}-{mean_motion}-{eccentricity}-{inclination}"
        tle_hash = hashlib.sha256(seed.encode()).hexdigest()
    return OrbitalElement(
        content_hash_source=content_hash_source,
        tle_index=tle_index,
        tle_content_hash=tle_hash,
        object_name=f"SAT-{norad}",
        norad_cat_id=norad,
        classification="U",
        intl_designator="24001A",
        epoch_year=epoch_dt.year,
        epoch_day=epoch_dt.timetuple().tm_yday + (epoch_dt.hour / 24.0),
        epoch_datetime=epoch_dt,
        mean_motion_dot=0.0,
        mean_motion_ddot=0.0,
        bstar=0.0,
        ephemeris_type=0,
        element_set_number=1,
        inclination_deg=inclination,
        raan_deg=0.0,
        eccentricity=eccentricity,
        arg_perigee_deg=0.0,
        mean_anomaly_deg=0.0,
        mean_motion=mean_motion,
        rev_number=0,
        engine_version="0.1.0",
        derived_at=DERIVED_AT,
    )


# --- S1–S8 -------------------------------------------------------------


def test_s1_series_rejects_empty_list() -> None:
    with pytest.raises(ValueError, match="len ≥ 2"):
        OrbitalElementSeries.from_elements([])


def test_s2_series_rejects_single_element() -> None:
    with pytest.raises(ValueError, match="len ≥ 2"):
        OrbitalElementSeries.from_elements([make_element()])


def test_s3_series_rejects_mixed_norad() -> None:
    a = make_element(norad=1, days_offset=0.0, tle_hash="a" * 64)
    b = make_element(norad=2, days_offset=1.0, tle_hash="b" * 64)
    with pytest.raises(ValueError, match="mismo norad_cat_id"):
        OrbitalElementSeries.from_elements([a, b])


def test_s4_series_rejects_non_monotonic_epochs() -> None:
    a = make_element(days_offset=2.0, tle_hash="a" * 64)
    b = make_element(days_offset=1.0, tle_hash="b" * 64)  # más viejo después
    with pytest.raises(ValueError, match="epochs estrictamente"):
        OrbitalElementSeries.from_elements([a, b])


def test_s5_series_rejects_equal_epochs() -> None:
    a = make_element(days_offset=1.0, tle_hash="a" * 64)
    b = make_element(days_offset=1.0, tle_hash="b" * 64)
    with pytest.raises(ValueError, match="epochs estrictamente"):
        OrbitalElementSeries.from_elements([a, b])


def test_s6_series_rejects_duplicate_tle_hashes() -> None:
    a = make_element(days_offset=0.0, tle_hash="a" * 64)
    b = make_element(days_offset=1.0, tle_hash="a" * 64)  # mismo hash
    with pytest.raises(ValueError, match="tle_content_hash duplicado"):
        OrbitalElementSeries.from_elements([a, b])


def test_s7_series_valid_two_element_minimum() -> None:
    a = make_element(days_offset=0.0, tle_hash="a" * 64)
    b = make_element(days_offset=1.0, tle_hash="b" * 64)
    series = OrbitalElementSeries.from_elements([a, b])
    assert series.n_elements == 2
    assert series.norad_cat_id == a.norad_cat_id


def test_s8_series_emits_start_end_epoch_correctly() -> None:
    els = [make_element(days_offset=float(i), tle_hash=f"{i:064x}") for i in range(5)]
    series = OrbitalElementSeries.from_elements(els)
    assert series.n_elements == 5
    assert series.series_start_epoch == els[0].epoch_datetime
    assert series.series_end_epoch == els[-1].epoch_datetime
