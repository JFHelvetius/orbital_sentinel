"""Tests del modelo ``Ephemeris`` (estructura del dato, sin propagación)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from orbital_sentinel.propagation import (
    EPHEMERIS_SCHEMA_VERSION,
    SGP4_PROPAGATOR_VERSION,
    Ephemeris,
)

DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)
EVAL = datetime(2008, 9, 20, 12, 25, 40, tzinfo=timezone.utc)


def _make(**overrides: Any) -> Ephemeris:
    defaults: dict[str, Any] = dict(
        orbital_element_content_hash_source="a" * 64,
        orbital_element_tle_index=0,
        tle_content_hash="b" * 64,
        norad_cat_id=25544,
        evaluation_time=EVAL,
        minutes_from_epoch=0.0,
        position_teme_x_km=4000.0,
        position_teme_y_km=-5000.0,
        position_teme_z_km=2000.0,
        velocity_teme_x_km_s=5.5,
        velocity_teme_y_km_s=4.0,
        velocity_teme_z_km_s=-3.0,
        sgp4_error_code=0,
        engine_version=SGP4_PROPAGATOR_VERSION,
        derived_at=DERIVED_AT,
    )
    defaults.update(overrides)
    return Ephemeris(**defaults)


def test_construction_with_defaults() -> None:
    e = _make()
    assert e.norad_cat_id == 25544
    assert e.sgp4_error_code == 0
    assert e.schema_version == EPHEMERIS_SCHEMA_VERSION
    assert e.engine_version == SGP4_PROPAGATOR_VERSION


def test_position_helper_returns_tuple() -> None:
    e = _make(position_teme_x_km=1.0, position_teme_y_km=2.0, position_teme_z_km=3.0)
    assert e.position_teme_km == (1.0, 2.0, 3.0)


def test_velocity_helper_returns_tuple() -> None:
    e = _make(velocity_teme_x_km_s=0.1, velocity_teme_y_km_s=0.2, velocity_teme_z_km_s=0.3)
    assert e.velocity_teme_km_s == (0.1, 0.2, 0.3)


def test_is_frozen() -> None:
    e = _make()
    with pytest.raises(Exception):
        e.norad_cat_id = 99999  # type: ignore[misc]


def test_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        Ephemeris.model_validate({**_make().model_dump(), "unexpected": 0})


def test_rejects_naive_evaluation_time() -> None:
    with pytest.raises(Exception):
        _make(evaluation_time=datetime(2008, 9, 20, 12, 0))  # type: ignore[arg-type]


def test_rejects_naive_derived_at() -> None:
    with pytest.raises(Exception):
        _make(derived_at=datetime(2026, 6, 3, 12, 0))  # type: ignore[arg-type]


def test_explicit_engine_version_preserved() -> None:
    e = _make(engine_version="0.99.99")
    assert e.engine_version == "0.99.99"


def test_schema_version_is_semver() -> None:
    e = _make()
    parts = e.schema_version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_error_code_preserved_when_nonzero() -> None:
    """Códigos != 0 no se filtran: ADR-0000 P2 honestidad sobre incertidumbre."""
    e = _make(sgp4_error_code=4)  # 4 = orbit decayed
    assert e.sgp4_error_code == 4
