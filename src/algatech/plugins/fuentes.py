"""Implementación de plugins de fuente S_i = A_i * h_i * u_i por tipo de pasivo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class FuentePasivo:
    """Descriptor de un tipo de pasivo ambiental capaz de aportar carga relativa S_i."""

    nombre: str
    calculador: Callable[[float, float | None, float | None, dict[str, Any]], float]


FUENTES_REGISTRADAS: dict[str, FuentePasivo] = {}


def registrar_fuente(nombre: str):
    """Decorador para registrar un plugin de fuente S_i por tipo de pasivo."""

    def _decorador(func: Callable[[float, float | None, float | None, dict[str, Any]], float]):
        FUENTES_REGISTRADAS[nombre] = FuentePasivo(nombre=nombre, calculador=func)
        return func

    return _decorador


def _calculo_estandar(
    area_m2: float,
    altura_m: float | None,
    factor_uso_hg: float | None,
    cfg_tipo: dict[str, Any],
) -> float:
    if area_m2 < 0:
        raise ValueError("area_m2 no puede ser negativa")
    h = float(altura_m) if altura_m is not None else float(cfg_tipo["altura_defecto_m"])
    u = float(factor_uso_hg) if factor_uso_hg is not None else float(cfg_tipo["factor_uso_hg_defecto"])
    if h < 0 or u < 0:
        raise ValueError("altura_m y factor_uso_hg deben ser no negativos")
    return float(area_m2) * h * u


@registrar_fuente("cola_aluvial")
def fuente_cola_aluvial(
    area_m2: float,
    altura_m: float | None,
    factor_uso_hg: float | None,
    cfg_fuentes: dict[str, Any],
) -> float:
    """Calcula S_i relativo para colas y relaves auríferos aluviales."""
    return _calculo_estandar(area_m2, altura_m, factor_uso_hg, cfg_fuentes["cola_aluvial"])


@registrar_fuente("desmonte")
def fuente_desmonte(
    area_m2: float,
    altura_m: float | None,
    factor_uso_hg: float | None,
    cfg_fuentes: dict[str, Any],
) -> float:
    """Calcula S_i relativo para desmontes y material estéril."""
    return _calculo_estandar(area_m2, altura_m, factor_uso_hg, cfg_fuentes["desmonte"])


@registrar_fuente("aguas_acidas")
def fuente_aguas_acidas(
    area_m2: float,
    altura_m: float | None,
    factor_uso_hg: float | None,
    cfg_fuentes: dict[str, Any],
) -> float:
    """Calcula S_i relativo para drenajes o lagunas con aguas ácidas."""
    return _calculo_estandar(area_m2, altura_m, factor_uso_hg, cfg_fuentes["aguas_acidas"])


def obtener_plugin_fuente(tipo_pasivo: str) -> FuentePasivo:
    """Obtiene el plugin registrado para un tipo de pasivo."""
    if tipo_pasivo not in FUENTES_REGISTRADAS:
        disponibles = ", ".join(sorted(FUENTES_REGISTRADAS))
        raise KeyError(f"Tipo de pasivo '{tipo_pasivo}' no registrado. Disponibles: {disponibles}")
    return FUENTES_REGISTRADAS[tipo_pasivo]


def calcular_fuerza_fuente(
    tipo_pasivo: str,
    area_m2: float,
    altura_m: float | None,
    factor_uso_hg: float | None,
    cfg_fuentes: dict[str, Any],
) -> float:
    """Despacha el cálculo de S_i al plugin correspondiente al tipo de pasivo."""
    plugin = obtener_plugin_fuente(tipo_pasivo)
    return plugin.calculador(area_m2, altura_m, factor_uso_hg, cfg_fuentes)
