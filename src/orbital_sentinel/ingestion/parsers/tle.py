"""Parser de Two-Line Element sets.

Implementa el formato definido en Spacetrack Report No. 3 (Hoots & Roehrich, 1980)
y revisado en Vallado et al. (2006). El parser es estricto por diseño: cualquier
desviación del formato eleva un error tipado con contexto de línea/columna.

Este módulo es la frontera de ingesta donde las cadenas laxas se convierten en
objetos validados. La validación cubre:

- Longitud canónica de cada línea (69 caracteres, ADR-0006 inmutabilidad por hash).
- Marcadores de línea (caracteres '1' y '2' en columna 1).
- Checksum mod-10 de cada línea.
- Consistencia del NORAD catalog number entre ambas líneas.
- Rangos físicos básicos (eccentricidad en [0, 1)).

El campo `content_hash` se calcula sobre el par canónico ``line1 + "\\n" + line2``
(excluye la línea de nombre porque distintas fuentes la formatean de forma distinta
para el mismo TLE; ver ADR-0006 sobre deduplicación content-addressable).

References:
    Hoots, F. R., & Roehrich, R. L. (1980). Spacetrack Report No. 3.
    Vallado, D. A. et al. (2006). Revisiting Spacetrack Report #3.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orbital_sentinel.core.errors import (
    TLEChecksumError,
    TLEFormatError,
    TLEInconsistencyError,
)

TLE_LINE_LENGTH = 69
"""Longitud canónica de cada línea TLE en caracteres."""

Classification = Literal["U", "C", "S"]


class TwoLineElement(BaseModel):
    """Conjunto de elementos en formato TLE, parseado y validado.

    La semántica de campos sigue Spacetrack Report No. 3. Los ángulos están
    en grados; los tiempos usan la convención de época TLE (año + día del año
    con fracción decimal). El año se expande a cuatro dígitos según la regla
    de Spacetrack (00-56 → 2000-2056, 57-99 → 1957-1999).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = Field(
        default=None,
        description="Línea de nombre (línea 0) si está presente en la fuente.",
    )
    norad_cat_id: int = Field(description="Número de catálogo NORAD (cinco dígitos).")
    classification: Classification = Field(description="Marca de clasificación U/C/S.")
    intl_designator: str = Field(
        description="Designador internacional, columnas 10-17 de la línea 1, rstripped."
    )
    epoch_year: int = Field(description="Año de la época, cuatro dígitos.")
    epoch_day: float = Field(description="Día del año de la época, con fracción.")
    mean_motion_dot: float = Field(
        description="Primera derivada de mean motion / 2 [rev/día^2]."
    )
    mean_motion_ddot: float = Field(
        description="Segunda derivada de mean motion / 6 [rev/día^3]."
    )
    bstar: float = Field(description="Término de drag BSTAR [1/radio terrestre].")
    ephemeris_type: int = Field(description="Tipo de efemérides. Típicamente 0.")
    element_set_number: int = Field(description="Número de element set del catálogo.")
    inclination_deg: float = Field(description="Inclinación [deg].")
    raan_deg: float = Field(description="Ascensión recta del nodo ascendente [deg].")
    eccentricity: float = Field(description="Eccentricidad (adimensional).")
    arg_perigee_deg: float = Field(description="Argumento del perigeo [deg].")
    mean_anomaly_deg: float = Field(description="Anomalía media [deg].")
    mean_motion: float = Field(description="Mean motion [rev/día].")
    rev_number: int = Field(description="Número de revolución en la época.")

    raw_line1: str = Field(description="Línea 1 original tal como se parseó.")
    raw_line2: str = Field(description="Línea 2 original tal como se parseó.")
    raw_name: str | None = Field(
        default=None, description="Línea de nombre original, si la hay."
    )

    content_hash: str = Field(
        description="SHA-256 hex de los bytes canónicos (line1 + '\\n' + line2)."
    )


def parse_tle(text: str) -> TwoLineElement:
    """Parsea un TLE desde texto.

    Args:
        text: Cadena que contiene el TLE. Opcionalmente puede incluir una
            línea de nombre como primera línea. Las líneas se separan por
            ``\\n`` o ``\\r\\n``. Tras quitar terminadores de línea, cada
            una de las dos líneas TLE debe tener exactamente 69 caracteres.

    Returns:
        Una instancia validada de :class:`TwoLineElement`.

    Raises:
        TLEFormatError: error estructural en la entrada.
        TLEChecksumError: el checksum declarado no coincide.
        TLEInconsistencyError: las dos líneas se contradicen.
    """
    lines = [ln.rstrip("\r\n") for ln in text.strip("\r\n").split("\n")]
    if len(lines) not in (2, 3):
        raise TLEFormatError(
            f"TLE debe contener 2 o 3 líneas (encontradas {len(lines)})"
        )

    if len(lines) == 3:
        name_raw = lines[0].rstrip()
        name = name_raw if name_raw else None
        line1, line2 = lines[1], lines[2]
    else:
        name = None
        line1, line2 = lines[0], lines[1]

    _validate_line(line1, line_number=1, expected_marker="1")
    _validate_line(line2, line_number=2, expected_marker="2")
    _verify_checksum(line1, line_number=1)
    _verify_checksum(line2, line_number=2)

    norad_1 = _parse_int(line1[2:7], line_number=1, col=3, field="NORAD ID")
    norad_2 = _parse_int(line2[2:7], line_number=2, col=3, field="NORAD ID")
    if norad_1 != norad_2:
        raise TLEInconsistencyError(
            f"NORAD ID no coincide entre líneas: {norad_1} vs {norad_2}",
            line=2,
            col=3,
        )

    classification_char = line1[7]
    if classification_char not in ("U", "C", "S"):
        raise TLEFormatError(
            f"Clasificación inválida '{classification_char}' (se esperaba U, C o S)",
            line=1,
            col=8,
        )

    intl_designator = line1[9:17].rstrip()

    epoch_year_2digit = _parse_int(
        line1[18:20], line_number=1, col=19, field="año de época"
    )
    epoch_day = _parse_float(line1[20:32], line_number=1, col=21, field="día de época")
    epoch_year = _expand_two_digit_year(epoch_year_2digit)

    mean_motion_dot = _parse_decimal_with_sign(
        line1[33:43], line_number=1, col=34, field="mean motion dot"
    )
    mean_motion_ddot = _parse_implied_decimal(
        line1[44:52], line_number=1, col=45, field="mean motion ddot"
    )
    bstar = _parse_implied_decimal(
        line1[53:61], line_number=1, col=54, field="BSTAR"
    )

    ephemeris_type = _parse_int(
        line1[62:63], line_number=1, col=63, field="tipo de efemérides"
    )
    element_set_number = _parse_int(
        line1[64:68], line_number=1, col=65, field="element set number"
    )

    inclination = _parse_float(
        line2[8:16], line_number=2, col=9, field="inclinación"
    )
    raan = _parse_float(line2[17:25], line_number=2, col=18, field="RAAN")
    eccentricity = _parse_eccentricity(line2[26:33], line_number=2, col=27)
    arg_perigee = _parse_float(
        line2[34:42], line_number=2, col=35, field="arg del perigeo"
    )
    mean_anomaly = _parse_float(
        line2[43:51], line_number=2, col=44, field="anomalía media"
    )
    mean_motion = _parse_float(
        line2[52:63], line_number=2, col=53, field="mean motion"
    )
    rev_number = _parse_int(
        line2[63:68], line_number=2, col=64, field="número de revolución"
    )

    canonical_bytes = (line1 + "\n" + line2).encode("ascii")
    content_hash = hashlib.sha256(canonical_bytes).hexdigest()

    return TwoLineElement(
        name=name,
        norad_cat_id=norad_1,
        classification=classification_char,  # type: ignore[arg-type]
        intl_designator=intl_designator,
        epoch_year=epoch_year,
        epoch_day=epoch_day,
        mean_motion_dot=mean_motion_dot,
        mean_motion_ddot=mean_motion_ddot,
        bstar=bstar,
        ephemeris_type=ephemeris_type,
        element_set_number=element_set_number,
        inclination_deg=inclination,
        raan_deg=raan,
        eccentricity=eccentricity,
        arg_perigee_deg=arg_perigee,
        mean_anomaly_deg=mean_anomaly,
        mean_motion=mean_motion,
        rev_number=rev_number,
        raw_line1=line1,
        raw_line2=line2,
        raw_name=name,
        content_hash=content_hash,
    )


def compute_checksum(line: str) -> int:
    """Calcula el dígito de checksum mod-10 según SR3.

    Suma todos los dígitos de la línea (excluyendo el último carácter, que es
    el propio checksum), contando cada signo menos como ``1`` y todo lo demás
    como ``0``, y devuelve el módulo 10 del resultado.
    """
    if not line:
        raise TLEFormatError("No se puede calcular checksum de línea vacía")
    body = line[:-1]
    total = 0
    for ch in body:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def _validate_line(line: str, *, line_number: int, expected_marker: str) -> None:
    if len(line) != TLE_LINE_LENGTH:
        raise TLEFormatError(
            f"La línea debe tener {TLE_LINE_LENGTH} caracteres (tiene {len(line)})",
            line=line_number,
        )
    if line[0] != expected_marker:
        raise TLEFormatError(
            f"La línea debe empezar por '{expected_marker}' (tiene '{line[0]}')",
            line=line_number,
            col=1,
        )


def _verify_checksum(line: str, *, line_number: int) -> None:
    expected_char = line[-1]
    if not expected_char.isdigit():
        raise TLEFormatError(
            f"La posición de checksum debe ser un dígito (tiene '{expected_char}')",
            line=line_number,
            col=TLE_LINE_LENGTH,
        )
    expected = int(expected_char)
    actual = compute_checksum(line)
    if actual != expected:
        raise TLEChecksumError(
            f"Checksum no coincide: declarado {expected}, calculado {actual}",
            line=line_number,
            col=TLE_LINE_LENGTH,
        )


def _parse_int(s: str, *, line_number: int, col: int, field: str) -> int:
    try:
        return int(s.strip())
    except ValueError as exc:
        raise TLEFormatError(
            f"No se pudo parsear '{field}' como entero desde '{s}'",
            line=line_number,
            col=col,
        ) from exc


def _parse_float(s: str, *, line_number: int, col: int, field: str) -> float:
    try:
        return float(s.strip())
    except ValueError as exc:
        raise TLEFormatError(
            f"No se pudo parsear '{field}' como float desde '{s}'",
            line=line_number,
            col=col,
        ) from exc


def _parse_decimal_with_sign(
    s: str, *, line_number: int, col: int, field: str
) -> float:
    """Parsea un campo decimal con signo y punto explícitos (mean motion dot)."""
    text = s.strip()
    try:
        return float(text)
    except ValueError as exc:
        raise TLEFormatError(
            f"No se pudo parsear '{field}' como decimal desde '{s}'",
            line=line_number,
            col=col,
        ) from exc


def _parse_implied_decimal(
    s: str, *, line_number: int, col: int, field: str
) -> float:
    """Parsea un campo con punto decimal implícito y exponente explícito.

    Formato: ``[+-]?MMMMM[+-]E`` donde la mantissa lleva un ``0.`` implícito
    y el exponente es un dígito con signo explícito.

    Ejemplos:
        ' 22500-3' -> 0.22500e-3 = 0.000225
        '-11606-4' -> -0.11606e-4 = -1.1606e-5
        ' 00000-0' -> 0.0
    """
    text = s.strip()
    if not text:
        return 0.0
    if len(text) < 3:
        raise TLEFormatError(
            f"Campo decimal implícito '{field}' demasiado corto: '{s}'",
            line=line_number,
            col=col,
        )

    sign = 1.0
    if text[0] in ("+", "-"):
        if text[0] == "-":
            sign = -1.0
        text = text[1:]

    exp_idx = max(text.rfind("+"), text.rfind("-"))
    if exp_idx <= 0:
        raise TLEFormatError(
            f"Campo decimal implícito '{field}' sin exponente explícito: '{s}'",
            line=line_number,
            col=col,
        )
    mantissa_str = text[:exp_idx]
    exponent_str = text[exp_idx:]
    try:
        mantissa = float("0." + mantissa_str)
        exponent = int(exponent_str)
    except ValueError as exc:
        raise TLEFormatError(
            f"No se pudo parsear '{field}' desde '{s}'",
            line=line_number,
            col=col,
        ) from exc
    result: float = sign * mantissa * (10**exponent)
    return result


def _parse_eccentricity(s: str, *, line_number: int, col: int) -> float:
    """Parsea eccentricidad (cols 27-33 de línea 2, punto decimal asumido)."""
    text = s.strip()
    if not text:
        return 0.0
    try:
        value = float("0." + text)
    except ValueError as exc:
        raise TLEFormatError(
            f"No se pudo parsear eccentricidad desde '{s}'",
            line=line_number,
            col=col,
        ) from exc
    if not 0.0 <= value < 1.0:
        raise TLEFormatError(
            f"Eccentricidad debe estar en [0, 1) (obtuve {value})",
            line=line_number,
            col=col,
        )
    return value


def _expand_two_digit_year(yy: int) -> int:
    """Expande el año de 2 dígitos a 4 según la convención Spacetrack.

    Años 57-99 -> 1957-1999, años 00-56 -> 2000-2056.
    """
    if 57 <= yy <= 99:
        return 1900 + yy
    if 0 <= yy <= 56:
        return 2000 + yy
    raise TLEFormatError(f"Año de dos dígitos fuera de rango: {yy}")
