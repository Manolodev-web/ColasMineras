"""Pruebas de Fase 0: configuración, plugins de fuente, esquema GPKG y datos simulados."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from algatech import SCHEMA_VERSION
from algatech.config import cargar_configuracion
from algatech.plugins import FUENTES_REGISTRADAS, calcular_fuerza_fuente
from algatech.schema import (
    CAPAS_OBLIGATORIAS,
    crear_esquema_geopackage,
    decode_gpkg_geom,
    encode_gpkg_geom,
    listar_tablas_gpkg,
    verificar_columnas_obligatorias,
)
from algatech.simulado import generar_gpkg_simulado
from shapely.geometry import Point


def test_cargar_configuracion_valida():
    cfg = cargar_configuracion()
    assert cfg.epsg_proyecto == 32719
    assert cfg.parametros["monte_carlo"]["n_sorteos"] == 500
    assert cfg.umbrales["umbrales_hg_mg_kg_ph"]["no_depredador"] == pytest.approx(0.5)
    assert cfg.umbrales["umbrales_hg_mg_kg_ph"]["depredador"] == pytest.approx(1.0)
    assert sum(
        [
            cfg.pesos["riesgo"]["peso_impacto_I"],
            cfg.pesos["riesgo"]["peso_poblacion_aguas_abajo"],
            cfg.pesos["riesgo"]["peso_agua_quieta"],
        ]
    ) == pytest.approx(1.0)


def test_plugins_fuentes_registradas():
    cfg = cargar_configuracion()
    for tipo in ("cola_aluvial", "desmonte", "aguas_acidas"):
        assert tipo in FUENTES_REGISTRADAS
        s_val = calcular_fuerza_fuente(tipo, 1000.0, None, None, cfg.parametros["fuentes"])
        assert s_val > 0.0

    with pytest.raises(ValueError):
        calcular_fuerza_fuente("cola_aluvial", -10.0, 2.0, 1.0, cfg.parametros["fuentes"])


def test_roundtrip_geometria_gpkg():
    pt = Point(620000.0, 8280000.0)
    blob = encode_gpkg_geom(pt, srid=32719)
    pt_out = decode_gpkg_geom(blob)
    assert pt_out is not None
    assert pt_out.equals(pt)


def test_esquema_geopackage_y_simulado(tmp_path: Path):
    ruta_vacio = tmp_path / "vacio.gpkg"
    crear_esquema_geopackage(ruta_vacio, srid_proyecto=32719, sobrescribir=True)
    verificar_columnas_obligatorias(ruta_vacio, CAPAS_OBLIGATORIAS)

    tablas = set(listar_tablas_gpkg(ruta_vacio))
    assert set(CAPAS_OBLIGATORIAS).issubset(tablas)
    assert "derechos_mineros" in tablas

    ruta_sim = tmp_path / "simulado.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta_sim)
    verificar_columnas_obligatorias(ruta_sim, CAPAS_OBLIGATORIAS)

    conn = sqlite3.connect(str(ruta_sim))
    try:
        ver = conn.execute(
            "SELECT valor FROM schema_metadata WHERE clave = 'schema_version'"
        ).fetchone()[0]
        assert ver == SCHEMA_VERSION

        for tabla in ("colas_candidatas", "fichas_campo", "tramos_rio", "puntos_receptores", "peces_hg", "derechos_mineros"):
            total = conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            no_sim = conn.execute(f"SELECT COUNT(*) FROM {tabla} WHERE sintetico != 1").fetchone()[0]
            assert total > 0, f"La tabla {tabla} debería tener registros simulados"
            assert no_sim == 0, f"La tabla {tabla} tiene registros sin marca sintetico=1"
    finally:
        conn.close()
