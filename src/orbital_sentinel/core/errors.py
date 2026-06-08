"""Jerarquía de errores del proyecto.

Las funciones internas pueden asumir invariantes; los puntos de entrada
(parsers, fetchers, APIs) validan en el borde y elevan estos errores con
contexto suficiente para diagnóstico sin acceso al runtime.
"""

from __future__ import annotations


class OrbitalSentinelError(Exception):
    """Raíz de todos los errores del proyecto."""


class IngestionError(OrbitalSentinelError):
    """Errores durante la ingesta de datos externos."""


class TLEParseError(IngestionError):
    """Base de los errores de parseo de TLE.

    Incluye contexto opcional (línea y columna) para localizar el problema
    sin necesidad de reproducir el run.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        col: int | None = None,
    ) -> None:
        self.line = line
        self.col = col
        location = ""
        if line is not None:
            location = f" (line {line}"
            if col is not None:
                location += f", col {col}"
            location += ")"
        super().__init__(f"{message}{location}")


class TLEFormatError(TLEParseError):
    """Error estructural: longitud de línea, marcador inválido, forma de campo."""


class TLEChecksumError(TLEParseError):
    """Dígito de checksum declarado no coincide con el calculado."""


class TLEInconsistencyError(TLEParseError):
    """Las dos líneas del TLE se contradicen (e.g., distinto NORAD ID)."""


class NormalizationError(IngestionError):
    """Error durante la normalización Raw → Normalized.

    Se eleva cuando un snapshot Raw no puede convertirse en filas Normalized
    de forma determinista (p. ej., un TLE malformado dentro de un snapshot
    multi-TLE). La normalización es estricta por diseño (ADR-0006): no se
    produce un resultado parcial silencioso.
    """


class PropagationError(OrbitalSentinelError):
    """Error durante la propagación Normalized → Derived (efemérides).

    Se eleva cuando:

    - El ``OrbitalElement`` y el ``TLESnapshot`` no son consistentes
      (``content_hash_source`` distinto).
    - La reconstrucción de las dos líneas TLE desde ``raw_text`` no coincide
      con ``tle_content_hash`` (corrupción cross-layer).
    - La librería SGP4 falla al inicializar la propagación (TLE estructuralmente
      no propagable).
    - Algún ``evaluation_time`` recibido no es timezone-aware (ADR-0013).

    **No se eleva** por códigos de error de SGP4 durante la propagación misma:
    esos se preservan en ``Ephemeris.sgp4_error_code`` para que el caller decida
    qué hacer (ADR-0000 P2 honestidad sobre incertidumbre).
    """


class AgentInputRejectedError(OrbitalSentinelError):
    """Un ``EvidenceBundle`` no pasó verificación; ``AgentInput`` no puede construirse.

    Adjunta el ``BundleVerificationReport`` para que el caller pueda inspeccionar
    los ``integrity_failures`` sin re-ejecutar el verifier. ADR-0032.
    """

    def __init__(self, message: str, *, verification_report: object) -> None:
        super().__init__(message)
        self.verification_report = verification_report


class ClaimRegistryBuilderError(OrbitalSentinelError):
    """El builder del :class:`ClaimRegistry` rechaza inputs incompatibles.

    Se eleva cuando el ``ExplanationArtifact`` y el ``AgentInput`` no son
    estructuralmente compatibles, o cuando el ``model_identifier`` del
    artifact no está soportado por la v0.1 (ADR-0035).
    """


class HypothesisRegistryBuilderError(OrbitalSentinelError):
    """El builder del :class:`HypothesisRegistry` rechaza inputs incompatibles.

    Se eleva cuando el ``ClaimRegistry`` y el ``AgentInput`` no comparten
    los mismos source IDs (ADR-0036).
    """


class EvidenceChainBuilderError(OrbitalSentinelError):
    """El builder del :class:`EvidenceChain` rechaza inputs incompatibles.

    Se eleva cuando los seis artefactos en cadena (hypothesis registry,
    claim registry, explanation artifact, agent input, bundle, evidence
    payloads) no se enlazan por sus identificadores content-addressable
    (ADR-0037).
    """


class InvestigationCaseBuilderError(OrbitalSentinelError):
    """El builder del :class:`InvestigationCase` rechaza inputs incompatibles.

    Se eleva cuando los artefactos embebidos no comparten una raíz común
    (ADR-0038).
    """


class RevocationLedgerBuilderError(OrbitalSentinelError):
    """El builder del :class:`RevocationLedger` rechaza inputs inconsistentes.

    Se eleva cuando los ``RevocationRecord`` aportados son incompatibles
    entre sí (duplicados de target, IDs inconsistentes) (ADR-0039).
    """


class ExternalSourceRegistryBuilderError(OrbitalSentinelError):
    """El builder del :class:`ExternalSourceRegistry` rechaza inputs incompatibles.

    Se eleva cuando los ``ExternalSourceRecord`` no cubren todas las
    evidencias del bundle objetivo o cuando el mapping evidence→source
    es inconsistente (ADR-0040).
    """


class DissentLedgerBuilderError(OrbitalSentinelError):
    """El builder del :class:`DissentLedger` rechaza inputs incompatibles.

    Se eleva cuando los ``DissentRecord`` no apuntan al mismo caso target
    o cuando las firmas content-addressable son inconsistentes (ADR-0041).
    """
