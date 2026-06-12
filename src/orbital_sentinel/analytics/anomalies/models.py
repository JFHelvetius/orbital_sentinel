"""Modelos públicos de detección de anomalías (ADR-0028).

Extensión del patrón ADR-0020 al dominio observacional general. Cada
``AnomalyEvent`` declara su contexto estadístico completo y porta
``is_apparent_not_confirmed=True``: reportamos desviaciones detectables,
no afirmamos causa, intención ni clasificación.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ANOMALY_DETECTION_SCHEMA_VERSION = "0.2.0"
"""SemVer del esquema (ADR-0010). 0.2.0: + content_hash_source (ADR-0043)."""

ANOMALY_DETECTION_ENGINE_VERSION = "0.2.0"
"""SemVer del motor de anomalías (ADR-0010 engine_version). 0.2.0: ADR-0043."""

DETECTION_METHOD_NAME = "self_baseline_z_score_v1"
"""Identificador del método (ADR-0028).

Distinto de ``element_jump_z_score_v1`` de ADR-0027: este detector
compara el VALOR observado contra una baseline de VALORES del mismo
objeto; el detector de maniobras compara TASAS DE CAMBIO contra baseline
de TASAS. Son señales independientes.
"""


class AnomalyEvent(BaseModel):
    """Una desviación observada del objeto respecto a su propia historia reciente.

    Reporte observacional. NO incluye causa, intención, clasificación ni
    score de "amenaza", "sospechoso" o similar — ADR-0028 lo prohíbe.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad del objeto ---
    object_id: str = Field(
        description="Identificador del objeto (``object_name`` si presente, "
        "si no ``NORAD-<id>``)."
    )
    norad_cat_id: int
    epoch_datetime: AwareDatetime

    # --- Provenance del punto observado (ADR-0043) ---
    content_hash_source: str = Field(
        description="content_hash_source del OrbitalElement observado; FK "
        "Normalized→Raw del TLE exacto que sustenta este finding (ADR-0043)."
    )

    # --- Feature observada ---
    feature_name: str
    observed_value: float
    baseline_mean: float
    baseline_stddev: float
    anomaly_score: float
    """Z-score signed: ``(observed_value − baseline_mean) / max(baseline_stddev, sigma_floor)``."""

    # --- Honesty fields (ADR-0028 § Honesty Requirements) ---
    detection_method_name: str = Field(default=DETECTION_METHOD_NAME)
    baseline_window_days: float = Field(gt=0.0)
    threshold_sigma: float = Field(gt=0.0)
    n_baseline_samples: int = Field(ge=1)
    is_apparent_not_confirmed: bool = Field(default=True)
    analysis_engine_version: str = Field(default=ANOMALY_DETECTION_ENGINE_VERSION)


class AnomalyDetectionConfig(BaseModel):
    """Configuración usada por la corrida (``configuration_used`` en
    :class:`AnomalyDetectionResult`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    features_used: list[str]
    baseline_window_days: float = Field(gt=0.0)
    threshold_sigma: float = Field(gt=0.0)
    min_baseline_samples: int = Field(ge=2)
    sigma_floor: float = Field(gt=0.0)
    detection_method_name: str = Field(default=DETECTION_METHOD_NAME)


class AnomalyDetectionResult(BaseModel):
    """Resultado completo de :func:`detect_anomalies` (ADR-0028)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Identidad de serie ---
    norad_cat_id: int
    object_id: str
    series_start_epoch: AwareDatetime
    series_end_epoch: AwareDatetime

    # --- Counts auditables ---
    total_objects_analyzed: int = Field(ge=1)
    total_anomalies_found: int = Field(ge=0)
    total_evaluations: int = Field(ge=0)
    total_evaluations_skipped_insufficient_baseline: int = Field(ge=0)

    # --- Configuración declarada (honesty) ---
    configuration_used: AnomalyDetectionConfig

    # --- Resultado ---
    events: list[AnomalyEvent]

    # --- Honesty global ---
    is_apparent_not_confirmed: bool = Field(default=True)

    # --- Versioning (ADR-0010) ---
    schema_version: str = Field(default=ANOMALY_DETECTION_SCHEMA_VERSION)
    analysis_engine_version: str = Field(default=ANOMALY_DETECTION_ENGINE_VERSION)
    derived_at: AwareDatetime
