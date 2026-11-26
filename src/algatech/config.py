"""Cargador centralizado de configuración YAML para AlgaTech."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@dataclass(frozen=True)
class ConfiguracionProyecto:
    """Agrupa todas las configuraciones parametrizadas por YAML."""

    zona: dict[str, Any]
    parametros: dict[str, Any]
    umbrales: dict[str, Any]
    pesos: dict[str, Any]

    @property
    def epsg_proyecto(self) -> int:
        crs = str(self.zona["crs_proyecto"])
        if ":" in crs:
            return int(crs.split(":")[-1])
        return int(crs)


def _leer_yaml(ruta: Path) -> dict[str, Any]:
    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de configuración no encontrado: {ruta}")
    with ruta.open("r", encoding="utf-8") as fh:
        datos = yaml.safe_load(fh)
    if not isinstance(datos, dict):
        raise ValueError(f"El archivo {ruta} debe contener un mapeo YAML válido.")
    return datos


def cargar_configuracion(config_dir: Path | str | None = None) -> ConfiguracionProyecto:
    """Carga y valida los cuatro archivos YAML del proyecto."""
    base = Path(config_dir) if config_dir is not None else DEFAULT_CONFIG_DIR
    zona = _leer_yaml(base / "zona.yaml")
    parametros = _leer_yaml(base / "parametros.yaml")
    umbrales = _leer_yaml(base / "umbrales.yaml")
    pesos = _leer_yaml(base / "pesos.yaml")

    for clave in ("crs_proyecto", "bbox_wgs84", "fechas"):
        if clave not in zona:
            raise KeyError(f"Falta clave obligatoria '{clave}' en zona.yaml")
    for clave in ("monte_carlo", "fuentes", "hidrologia"):
        if clave not in parametros:
            raise KeyError(f"Falta clave obligatoria '{clave}' en parametros.yaml")
    for clave in ("umbrales_hg_mg_kg_ph", "semaforo"):
        if clave not in umbrales:
            raise KeyError(f"Falta clave obligatoria '{clave}' en umbrales.yaml")
    for clave in ("riesgo", "economia_referencia", "cuadrantes"):
        if clave not in pesos:
            raise KeyError(f"Falta clave obligatoria '{clave}' en pesos.yaml")

    return ConfiguracionProyecto(
        zona=zona,
        parametros=parametros,
        umbrales=umbrales,
        pesos=pesos,
    )
