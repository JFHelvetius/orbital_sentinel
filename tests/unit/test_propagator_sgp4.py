"""Tests del propagador SGP4: integración con la librería + trazabilidad."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sgp4.api import Satrec, jday

from orbital_sentinel.catalog import TLESnapshot, normalize_snapshot
from orbital_sentinel.core.errors import PropagationError
from orbital_sentinel.propagation import (
    EPHEMERIS_SCHEMA_VERSION,
    SGP4_PROPAGATOR_VERSION,
    Ephemeris,
    Sgp4Propagator,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"
DERIVED_AT = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


def _make_snapshot_from_fixture(name: str = "iss_vallado_2008.txt") -> TLESnapshot:
    text = (FIXTURES / name).read_text(encoding="ascii")
    encoded = text.encode("ascii")
    return TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
        fetched_at=DERIVED_AT,
        raw_text=text,
        n_bytes=len(encoded),
    )


def _iss_element_and_snapshot():
    snap = _make_snapshot_from_fixture()
    [element] = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return element, snap


def _multi_element_and_snapshot():
    snap = _make_snapshot_from_fixture("multi_stations.txt")
    elements = normalize_snapshot(snap, derived_at=DERIVED_AT)
    return elements, snap


# --- Construcción y resultado básico --------------------------------------


def test_propagate_at_epoch_returns_one_ephemeris() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    ephemerides = prop.propagate(element, snap, [element.epoch_datetime])
    assert len(ephemerides) == 1
    assert isinstance(ephemerides[0], Ephemeris)
    assert ephemerides[0].sgp4_error_code == 0


def test_propagate_empty_times_returns_empty_list() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    assert prop.propagate(element, snap, []) == []


def test_propagate_at_multiple_times_returns_same_cardinality() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    times = [element.epoch_datetime + timedelta(minutes=15 * i) for i in range(4)]
    ephemerides = prop.propagate(element, snap, times)
    assert len(ephemerides) == 4
    for t, e in zip(times, ephemerides, strict=True):
        assert e.evaluation_time == t


def test_propagate_at_epoch_convenience() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    a = prop.propagate_at_epoch(element, snap)
    b = prop.propagate(element, snap, [element.epoch_datetime])[0]
    assert a.model_dump() == b.model_dump()


# --- Sanidad física --------------------------------------------------------


def test_position_magnitude_in_leo_range() -> None:
    """ISS está en LEO: |r| ≈ 6700–7000 km."""
    element, snap = _iss_element_and_snapshot()
    [e] = Sgp4Propagator().propagate(element, snap, [element.epoch_datetime])
    r_mag = math.sqrt(
        e.position_teme_x_km**2 + e.position_teme_y_km**2 + e.position_teme_z_km**2
    )
    assert 6600 < r_mag < 7100, f"Esperaba rango LEO; obtuve {r_mag} km"


def test_velocity_magnitude_in_leo_range() -> None:
    """ISS está en LEO: |v| ≈ 7.5–7.8 km/s."""
    element, snap = _iss_element_and_snapshot()
    [e] = Sgp4Propagator().propagate(element, snap, [element.epoch_datetime])
    v_mag = math.sqrt(
        e.velocity_teme_x_km_s**2 + e.velocity_teme_y_km_s**2 + e.velocity_teme_z_km_s**2
    )
    assert 7.4 < v_mag < 7.9, f"Esperaba velocidad LEO; obtuve {v_mag} km/s"


def test_propagation_far_from_epoch_still_returns() -> None:
    """t = epoch + 3 días aún produce resultado (con o sin error code != 0)."""
    element, snap = _iss_element_and_snapshot()
    far = element.epoch_datetime + timedelta(days=3)
    [e] = Sgp4Propagator().propagate(element, snap, [far])
    assert isinstance(e, Ephemeris)


# --- Golden master contra la librería sgp4 directamente -------------------


def test_wrapper_matches_sgp4_lib_bit_exact() -> None:
    """Nuestro wrapper produce los mismos números que sgp4 llamado directamente.

    Esta es la prueba de no-regresión más fuerte: garantiza que el wrapper no
    introduce desviaciones numéricas respecto a la librería de referencia.
    """
    text = (FIXTURES / "iss_vallado_2008.txt").read_text(encoding="ascii")
    lines = text.strip().split("\n")
    line1, line2 = lines[1], lines[2]

    sat = Satrec.twoline2rv(line1, line2)
    epoch_dt = datetime(2008, 9, 20, 0, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=(264.51782528 - 264) * 86400
    )
    # La fecha exacta: 2008 día 264.51782528 = 2008-09-20 + 0.51782528 días.
    jd_int, fr = jday(
        epoch_dt.year,
        epoch_dt.month,
        epoch_dt.day,
        epoch_dt.hour,
        epoch_dt.minute,
        epoch_dt.second + epoch_dt.microsecond * 1e-6,
    )
    expected_err, expected_r, expected_v = sat.sgp4(jd_int, fr)

    element, snap = _iss_element_and_snapshot()
    [e] = Sgp4Propagator().propagate(element, snap, [epoch_dt])

    assert e.sgp4_error_code == expected_err
    assert e.position_teme_x_km == float(expected_r[0])
    assert e.position_teme_y_km == float(expected_r[1])
    assert e.position_teme_z_km == float(expected_r[2])
    assert e.velocity_teme_x_km_s == float(expected_v[0])
    assert e.velocity_teme_y_km_s == float(expected_v[1])
    assert e.velocity_teme_z_km_s == float(expected_v[2])


# --- Trazabilidad ---------------------------------------------------------


def test_provenance_fields_populated() -> None:
    element, snap = _iss_element_and_snapshot()
    [e] = Sgp4Propagator().propagate(element, snap, [element.epoch_datetime])
    assert e.orbital_element_content_hash_source == element.content_hash_source
    assert e.orbital_element_content_hash_source == snap.content_hash
    assert e.orbital_element_tle_index == element.tle_index
    assert e.tle_content_hash == element.tle_content_hash
    assert e.norad_cat_id == element.norad_cat_id


def test_engine_and_schema_versions_stamped() -> None:
    element, snap = _iss_element_and_snapshot()
    [e] = Sgp4Propagator().propagate(element, snap, [element.epoch_datetime])
    assert e.engine_version == SGP4_PROPAGATOR_VERSION
    assert e.schema_version == EPHEMERIS_SCHEMA_VERSION


def test_minutes_from_epoch_signed() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    [past, here, future] = prop.propagate(
        element,
        snap,
        [
            element.epoch_datetime - timedelta(minutes=30),
            element.epoch_datetime,
            element.epoch_datetime + timedelta(minutes=45),
        ],
    )
    assert past.minutes_from_epoch == pytest.approx(-30.0, abs=1e-6)
    assert here.minutes_from_epoch == pytest.approx(0.0, abs=1e-6)
    assert future.minutes_from_epoch == pytest.approx(45.0, abs=1e-6)


def test_derived_at_uses_clock() -> None:
    element, snap = _iss_element_and_snapshot()
    fixed = datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)
    prop = Sgp4Propagator(clock=lambda: fixed)
    [e] = prop.propagate(element, snap, [element.epoch_datetime])
    assert e.derived_at == fixed


def test_derived_at_shared_across_batch() -> None:
    """derived_at se materializa una vez por llamada y se comparte entre outputs."""
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator()
    ephemerides = prop.propagate(
        element,
        snap,
        [element.epoch_datetime + timedelta(minutes=i) for i in range(3)],
    )
    derived_ats = {e.derived_at for e in ephemerides}
    assert len(derived_ats) == 1


# --- Determinismo ---------------------------------------------------------


def test_propagation_is_deterministic() -> None:
    element, snap = _iss_element_and_snapshot()
    prop = Sgp4Propagator(clock=lambda: DERIVED_AT)
    a = prop.propagate(element, snap, [element.epoch_datetime])
    b = prop.propagate(element, snap, [element.epoch_datetime])
    assert [e.model_dump() for e in a] == [e.model_dump() for e in b]


# --- Validación defensiva -------------------------------------------------


def test_rejects_mismatched_element_and_snapshot() -> None:
    """element.content_hash_source distinto del snapshot.content_hash → raise."""
    element, _ = _iss_element_and_snapshot()
    other_snap_text = (
        "ISS (ZARYA)\n"
        "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927\n"
        "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537\n"
        "PADDING-DIFFERENT-HASH\n"
    )
    encoded = other_snap_text.encode("ascii")
    other_snap = TLESnapshot(
        content_hash=hashlib.sha256(encoded).hexdigest(),
        source="celestrak",
        dataset="stations",
        url="https://example/",
        fetched_at=DERIVED_AT,
        raw_text=other_snap_text,
        n_bytes=len(encoded),
    )
    with pytest.raises(PropagationError, match="inconsistentes"):
        Sgp4Propagator().propagate(element, other_snap, [element.epoch_datetime])


def test_rejects_naive_evaluation_time() -> None:
    element, snap = _iss_element_and_snapshot()
    with pytest.raises(PropagationError, match="timezone-aware"):
        Sgp4Propagator().propagate(element, snap, [datetime(2008, 9, 20, 12, 0)])


def test_rejects_when_tle_index_out_of_range() -> None:
    """Si el element apunta a un tle_index inexistente en el snapshot, raise."""
    elements, snap = _multi_element_and_snapshot()
    fake = elements[0].model_copy(update={"tle_index": 99})
    with pytest.raises(PropagationError, match="no encontrado"):
        Sgp4Propagator().propagate(fake, snap, [fake.epoch_datetime])


def test_rejects_when_tle_hash_mismatch() -> None:
    """Si las líneas reconstruidas no coinciden con el hash declarado, raise.

    Esto detecta corrupción cross-layer: alguien insertó un OrbitalElement con
    un ``tle_content_hash`` que no corresponde al TLE realmente almacenado en
    el snapshot.
    """
    element, snap = _iss_element_and_snapshot()
    tampered = element.model_copy(update={"tle_content_hash": "f" * 64})
    with pytest.raises(PropagationError, match="no coincide"):
        Sgp4Propagator().propagate(tampered, snap, [element.epoch_datetime])


# --- Multi-TLE snapshot ---------------------------------------------------


def test_propagates_each_element_independently_in_multi_snapshot() -> None:
    elements, snap = _multi_element_and_snapshot()
    prop = Sgp4Propagator()
    ephem_iss = prop.propagate(elements[0], snap, [elements[0].epoch_datetime])[0]
    ephem_test = prop.propagate(elements[1], snap, [elements[1].epoch_datetime])[0]
    assert ephem_iss.norad_cat_id == 25544
    assert ephem_test.norad_cat_id == 99999
    # Posiciones distintas porque son objetos diferentes
    assert ephem_iss.position_teme_km != ephem_test.position_teme_km
