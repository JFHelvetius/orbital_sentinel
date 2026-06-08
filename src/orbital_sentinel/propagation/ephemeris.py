"""Modelo de datos ``Ephemeris``: primera tabla virtual de la capa Derived.

Cada ``Ephemeris`` representa el **vector de estado** (posición + velocidad) de
un objeto en un instante determinado, derivado mediante SGP4 a partir de un
``OrbitalElement`` (Normalized) que a su vez procede de un ``TLESnapshot`` (Raw).

Marco de referencia: **TEME** (True Equator, Mean Equinox) — el marco nativo
de SGP4. Unidades: kilómetros y kilómetros por segundo. Cualquier conversión a
ECI, ECEF, ITRF u otros marcos es responsabilidad de capas superiores; el motor
no transforma marcos por sí mismo.

Persistencia: **on-demand por defecto** (ADR-0006 enmienda 1). Este modelo
existe primariamente en memoria. Si en el futuro se introduce caché o
persistencia opcional, este mismo modelo se serializará a Parquet, pero v1 no
asume persistencia.

Trazabilidad inversa:

    Ephemeris.orbital_element_content_hash_source → TLESnapshot.content_hash
    Ephemeris.orbital_element_tle_index           → OrbitalElement.tle_index
    Ephemeris.tle_content_hash                    → OrbitalElement.tle_content_hash
    Ephemeris.norad_cat_id                        → OrbitalElement.norad_cat_id

La denormalización de ``norad_cat_id`` se justifica explícitamente:
las queries operacionales casi siempre filtran por NORAD ID, y forzar un JOIN
con ``orbital_elements`` por cada query degrada UX sin ganar nada.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EPHEMERIS_SCHEMA_VERSION = "0.1.0"
"""SemVer del esquema de Ephemeris (ADR-0010)."""


class Ephemeris(BaseModel):
    """Vector de estado derivado de un ``OrbitalElement`` en un instante UTC.

    Pertenencia de campos (ver docs/architecture/layers.md):

    * **Provenance** (FK a Normalized y, transitivamente, a Raw):
      ``orbital_element_content_hash_source``, ``orbital_element_tle_index``,
      ``tle_content_hash``.
    * **Identity** (denormalizado para queries hot-path):
      ``norad_cat_id``.
    * **Evaluation context**:
      ``evaluation_time`` (instante UTC), ``minutes_from_epoch`` (signo +/-).
    * **State vector** (TEME):
      ``position_teme_x_km``, ``position_teme_y_km``, ``position_teme_z_km``,
      ``velocity_teme_x_km_s``, ``velocity_teme_y_km_s``, ``velocity_teme_z_km_s``.
    * **Quality**: ``sgp4_error_code`` (0 = OK, 1–7 = códigos SGP4).
    * **Versioning** (ADR-0010): ``schema_version``, ``engine_version``,
      ``derived_at``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Provenance ---
    orbital_element_content_hash_source: str = Field(
        description="FK lógica a tle_snapshots.content_hash."
    )
    orbital_element_tle_index: int = Field(
        description="Posición 0-based del TLE en el snapshot fuente."
    )
    tle_content_hash: str = Field(
        description="SHA-256 hex del TLE individual (line1+\\n+line2)."
    )
    norad_cat_id: int = Field(
        description="Número de catálogo NORAD, denormalizado para queries hot-path."
    )

    # --- Evaluation context ---
    evaluation_time: AwareDatetime = Field(
        description="Instante UTC al que se evaluó la propagación."
    )
    minutes_from_epoch: float = Field(
        description="Minutos desde la época del TLE (signo + futuro, - pasado)."
    )

    # --- State vector (TEME, km, km/s) ---
    position_teme_x_km: float = Field(description="Componente X de posición TEME [km].")
    position_teme_y_km: float = Field(description="Componente Y de posición TEME [km].")
    position_teme_z_km: float = Field(description="Componente Z de posición TEME [km].")
    velocity_teme_x_km_s: float = Field(
        description="Componente X de velocidad TEME [km/s]."
    )
    velocity_teme_y_km_s: float = Field(
        description="Componente Y de velocidad TEME [km/s]."
    )
    velocity_teme_z_km_s: float = Field(
        description="Componente Z de velocidad TEME [km/s]."
    )

    # --- Quality ---
    sgp4_error_code: int = Field(
        description=(
            "Código de error devuelto por sgp4. 0 = OK; 1-7 = condiciones "
            "anómalas (excentricidad fuera de rango, decaída, etc.). "
            "El valor se preserva para que el caller decida; el wrapper no "
            "filtra ni descarta. ADR-0000 P2."
        )
    )

    # --- Versioning + derivation context (ADR-0010) ---
    schema_version: str = Field(
        default=EPHEMERIS_SCHEMA_VERSION,
        description="Versión del esquema (ADR-0010).",
    )
    engine_version: str = Field(
        description="SemVer del propagador (ADR-0010 engine_version)."
    )
    derived_at: AwareDatetime = Field(
        description="UTC timestamp de la derivación."
    )

    @property
    def position_teme_km(self) -> tuple[float, float, float]:
        """Helper: devuelve la posición como tupla 3D."""
        return (self.position_teme_x_km, self.position_teme_y_km, self.position_teme_z_km)

    @property
    def velocity_teme_km_s(self) -> tuple[float, float, float]:
        """Helper: devuelve la velocidad como tupla 3D."""
        return (
            self.velocity_teme_x_km_s,
            self.velocity_teme_y_km_s,
            self.velocity_teme_z_km_s,
        )
