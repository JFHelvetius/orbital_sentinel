"""Tests del módulo ``propagation.frames`` (ADR-0023, fase 1 refactor).

Cubre:

* F1 GMST IAU 1982 en J2000.0 (valor analítico exacto del término constante).
* F2 ``teme_to_ecef`` es rotación pura alrededor de Z (3 vectores canónicos).
* F3 ``teme_to_ecef`` preserva la componente Z.
* F4 ``teme_to_ecef`` preserva la norma del vector.
* F5 Regression: ``groundtrack.{gmst_radians,teme_to_ecef}`` delega bit-exacto
     en ``frames`` tras la extracción.
* F6 ``GMST_MODEL_NAME`` declara la asunción UT1 ≈ UTC (enmienda ADR-0023).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from orbital_sentinel.propagation.frames import (
    GMST_MODEL_NAME,
    gmst_iau_1982,
    teme_to_ecef,
)

J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
"""Epoch J2000.0 nominal: en este instante el término ``(jd - 2451545.0)`` del
formulario IAU 1982 es exactamente cero, y por tanto GMST = 280.46061837°.
"""


# --- F1 ------------------------------------------------------------------


def test_gmst_iau_1982_vallado_reference() -> None:
    """En J2000.0 todos los términos no-constantes son cero: GMST = 280.46061837°."""
    expected_rad = math.radians(280.46061837)
    assert gmst_iau_1982(J2000) == pytest.approx(expected_rad, abs=1e-12)


# --- F2 ------------------------------------------------------------------


def test_teme_to_ecef_pure_z_rotation() -> None:
    """``teme_to_ecef`` es rotación pura alrededor de Z con ángulo GMST.

    Tres vectores canónicos fijan la matriz íntegra:

    * (1, 0, 0) → ( cos g, -sin g, 0)
    * (0, 1, 0) → ( sin g,  cos g, 0)
    * (0, 0, 1) → (    0,      0, 1)
    """
    when = datetime(2008, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    g = gmst_iau_1982(when)
    cos_g, sin_g = math.cos(g), math.sin(g)

    rx, ry, rz = teme_to_ecef(1.0, 0.0, 0.0, when)
    assert rx == pytest.approx(cos_g, abs=1e-15)
    assert ry == pytest.approx(-sin_g, abs=1e-15)
    assert rz == 0.0

    rx, ry, rz = teme_to_ecef(0.0, 1.0, 0.0, when)
    assert rx == pytest.approx(sin_g, abs=1e-15)
    assert ry == pytest.approx(cos_g, abs=1e-15)
    assert rz == 0.0

    rx, ry, rz = teme_to_ecef(0.0, 0.0, 1.0, when)
    assert (rx, ry, rz) == (0.0, 0.0, 1.0)


# --- F3 ------------------------------------------------------------------


def test_teme_to_ecef_preserves_z() -> None:
    """La rotación TEME→ECEF es alrededor del eje Z; Z no cambia."""
    when = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    _, _, z = teme_to_ecef(1234.5, -6789.0, 4321.0, when)
    assert z == 4321.0


# --- F4 ------------------------------------------------------------------


def test_teme_to_ecef_preserves_norm() -> None:
    """La rotación TEME→ECEF preserva la norma del vector."""
    when = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    x, y, z = 7000.0, -3000.0, 1500.0
    norm_in = math.sqrt(x * x + y * y + z * z)
    rx, ry, rz = teme_to_ecef(x, y, z, when)
    norm_out = math.sqrt(rx * rx + ry * ry + rz * rz)
    assert norm_out == pytest.approx(norm_in, rel=1e-12)


# --- F5 ------------------------------------------------------------------


def test_groundtrack_callables_match_frames_after_extraction() -> None:
    """Regression: tras el refactor preparatorio de ADR-0023, los símbolos
    ``gmst_radians`` y ``teme_to_ecef`` que ``groundtrack`` expone delegan
    bit-exacto en ``propagation.frames``.

    Este test fija ese contrato y bloquea divergencias futuras: cualquier
    duplicación silenciosa o re-implementación local en ``groundtrack`` rompe
    la igualdad.
    """
    from orbital_sentinel.orchestration import groundtrack as gt
    from orbital_sentinel.propagation import frames as fr

    sample_times = [
        datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2008, 9, 20, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
    ]
    for t in sample_times:
        assert gt.gmst_radians(t) == fr.gmst_iau_1982(t)
        assert gt.teme_to_ecef(1234.5, -6789.0, 4321.0, t) == fr.teme_to_ecef(
            1234.5, -6789.0, 4321.0, t
        )


def test_groundtrack_gmst_radians_is_alias_of_frames_gmst_iau_1982() -> None:
    """``groundtrack.gmst_radians`` es exactamente el callable de ``frames``.

    Identidad por ``is`` — no hay segunda definición ni wrapper.
    """
    from orbital_sentinel.orchestration import groundtrack as gt
    from orbital_sentinel.propagation import frames as fr

    assert gt.gmst_radians is fr.gmst_iau_1982


# --- F6 ------------------------------------------------------------------


def test_gmst_model_name_declares_ut1_assumption() -> None:
    """``GMST_MODEL_NAME`` encodea la asunción UT1 ≈ UTC (ADR-0023 enmienda 4).

    El string es contrato machine-readable: una eventual implementación con
    DUT1 IERS real requerirá un identificador distinto.
    """
    assert GMST_MODEL_NAME == "iau_1982_ut1_equals_utc_v1"
