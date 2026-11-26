"""Plugins extensibles de cálculo de fuerza de fuente S_i por tipo de pasivo."""

from algatech.plugins.fuentes import (
    FuentePasivo,
    FUENTES_REGISTRADAS,
    calcular_fuerza_fuente,
    obtener_plugin_fuente,
    registrar_fuente,
)

__all__ = [
    "FuentePasivo",
    "FUENTES_REGISTRADAS",
    "calcular_fuerza_fuente",
    "obtener_plugin_fuente",
    "registrar_fuente",
]
