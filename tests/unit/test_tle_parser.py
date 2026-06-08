"""Tests del parser TLE.

Cubren tres niveles según ADR-0000 P4 (validación operacional de reproducibilidad):

- Regresión sobre vectores canónicos (TLE ISS Vallado 2008).
- Validación de invariantes estructurales (longitud, marcadores, checksums).
- Comportamiento de errores tipados con contexto de línea/columna.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orbital_sentinel.core.errors import (
    TLEChecksumError,
    TLEFormatError,
    TLEInconsistencyError,
)
from orbital_sentinel.ingestion.parsers.tle import (
    TLE_LINE_LENGTH,
    TwoLineElement,
    compute_checksum,
    parse_tle,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tle"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="ascii")


# ---------------------------------------------------------------------------
# Regresión sobre el TLE canónico de Vallado (ISS, 2008-09-20)
# ---------------------------------------------------------------------------


def test_parses_iss_canonical_tle() -> None:
    text = _load("iss_vallado_2008.txt")
    tle = parse_tle(text)

    assert isinstance(tle, TwoLineElement)
    assert tle.name == "ISS (ZARYA)"
    assert tle.norad_cat_id == 25544
    assert tle.classification == "U"
    assert tle.intl_designator == "98067A"
    assert tle.epoch_year == 2008
    assert tle.epoch_day == pytest.approx(264.51782528, abs=1e-8)
    assert tle.mean_motion_dot == pytest.approx(-2.182e-5, rel=1e-4)
    assert tle.mean_motion_ddot == pytest.approx(0.0, abs=1e-12)
    assert tle.bstar == pytest.approx(-1.1606e-5, rel=1e-4)
    assert tle.ephemeris_type == 0
    assert tle.element_set_number == 292
    assert tle.inclination_deg == pytest.approx(51.6416)
    assert tle.raan_deg == pytest.approx(247.4627)
    assert tle.eccentricity == pytest.approx(0.0006703)
    assert tle.arg_perigee_deg == pytest.approx(130.5360)
    assert tle.mean_anomaly_deg == pytest.approx(325.0288)
    assert tle.mean_motion == pytest.approx(15.72125391)
    assert tle.rev_number == 56353


def test_parses_without_name_line() -> None:
    text = _load("iss_vallado_2008_no_name.txt")
    tle = parse_tle(text)
    assert tle.name is None
    assert tle.raw_name is None
    assert tle.norad_cat_id == 25544


def test_raw_lines_preserved() -> None:
    text = _load("iss_vallado_2008.txt")
    tle = parse_tle(text)
    assert len(tle.raw_line1) == TLE_LINE_LENGTH
    assert len(tle.raw_line2) == TLE_LINE_LENGTH
    assert tle.raw_line1.startswith("1 25544U")
    assert tle.raw_line2.startswith("2 25544")


# ---------------------------------------------------------------------------
# Propiedades del content_hash (ADR-0006 deduplicación content-addressable)
# ---------------------------------------------------------------------------


def test_content_hash_is_sha256_hex() -> None:
    tle = parse_tle(_load("iss_vallado_2008.txt"))
    assert len(tle.content_hash) == 64
    int(tle.content_hash, 16)  # debe ser hex válido


def test_content_hash_is_deterministic() -> None:
    text = _load("iss_vallado_2008.txt")
    assert parse_tle(text).content_hash == parse_tle(text).content_hash


def test_content_hash_ignores_name_line() -> None:
    """El hash se calcula sobre (line1, line2) — la línea de nombre no influye.

    Esto permite que dos fuentes que publican el mismo TLE con distinta línea
    de nombre se deduplican automáticamente.
    """
    with_name = parse_tle(_load("iss_vallado_2008.txt"))
    without_name = parse_tle(_load("iss_vallado_2008_no_name.txt"))
    assert with_name.content_hash == without_name.content_hash


# ---------------------------------------------------------------------------
# Errores estructurales
# ---------------------------------------------------------------------------


VALID_LINE1 = "1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927"
VALID_LINE2 = "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537"


def test_rejects_wrong_line_length() -> None:
    short_line1 = VALID_LINE1[:-1]  # 68 chars
    bad = f"{short_line1}\n{VALID_LINE2}\n"
    with pytest.raises(TLEFormatError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 1


def test_rejects_bad_line_marker() -> None:
    bad_line1 = "X" + VALID_LINE1[1:]
    bad = f"{bad_line1}\n{VALID_LINE2}\n"
    with pytest.raises(TLEFormatError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 1
    assert exc_info.value.col == 1


def test_rejects_only_one_line() -> None:
    with pytest.raises(TLEFormatError):
        parse_tle(VALID_LINE1 + "\n")


def test_rejects_four_lines() -> None:
    bad = f"ISS\nEXTRA\n{VALID_LINE1}\n{VALID_LINE2}\n"
    with pytest.raises(TLEFormatError):
        parse_tle(bad)


# ---------------------------------------------------------------------------
# Errores de checksum
# ---------------------------------------------------------------------------


def test_rejects_bad_checksum_line1() -> None:
    # Cambia el último dígito de '7' a '0': declarado 0, calculado 7.
    bad_line1 = VALID_LINE1[:-1] + "0"
    bad = f"{bad_line1}\n{VALID_LINE2}\n"
    with pytest.raises(TLEChecksumError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 1


def test_rejects_bad_checksum_line2() -> None:
    bad_line2 = VALID_LINE2[:-1] + "0"
    bad = f"{VALID_LINE1}\n{bad_line2}\n"
    with pytest.raises(TLEChecksumError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 2


# ---------------------------------------------------------------------------
# Inconsistencias entre líneas
# ---------------------------------------------------------------------------


def test_rejects_inconsistent_norad_ids() -> None:
    """Línea 2 con NORAD 25543 (diff -1 sobre línea 1).

    Sum digits diff = -1, así que el checksum debe ser 6 en vez de 7.
    """
    inconsistent_line2 = (
        "2 25543  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563536"
    )
    bad = f"{VALID_LINE1}\n{inconsistent_line2}\n"
    with pytest.raises(TLEInconsistencyError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 2


# ---------------------------------------------------------------------------
# Errores semánticos
# ---------------------------------------------------------------------------


def test_rejects_invalid_classification() -> None:
    """Cambiar 'U' por 'X' en col 8 (sum digits no cambia, checksum sigue siendo válido)."""
    bad_line1 = VALID_LINE1[:7] + "X" + VALID_LINE1[8:]
    bad = f"{bad_line1}\n{VALID_LINE2}\n"
    with pytest.raises(TLEFormatError) as exc_info:
        parse_tle(bad)
    assert exc_info.value.line == 1
    assert exc_info.value.col == 8


# ---------------------------------------------------------------------------
# Compute checksum como función pública (regresión sobre TLE conocido)
# ---------------------------------------------------------------------------


def test_compute_checksum_matches_canonical_lines() -> None:
    assert compute_checksum(VALID_LINE1) == 7
    assert compute_checksum(VALID_LINE2) == 7


def test_compute_checksum_counts_minus_as_one() -> None:
    # Línea sintética: "1-9" -> dígitos 1+9=10, menos cuenta 1, total 11 mod 10 = 1.
    # El último char es la posición del checksum, así que body es "1-9".
    line = "1-9X"  # X es placeholder para el char checksum, ignorado.
    assert compute_checksum(line) == (1 + 1 + 9) % 10


def test_compute_checksum_empty_raises() -> None:
    with pytest.raises(TLEFormatError):
        compute_checksum("")


# ---------------------------------------------------------------------------
# Frozen / extra forbid del modelo Pydantic (regresión sobre ConfigDict)
# ---------------------------------------------------------------------------


def test_model_is_frozen() -> None:
    tle = parse_tle(_load("iss_vallado_2008.txt"))
    with pytest.raises(Exception):  # pydantic ValidationError o FrozenInstanceError
        tle.norad_cat_id = 99999  # type: ignore[misc]
