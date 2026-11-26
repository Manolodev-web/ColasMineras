"""Pruebas de M1 detección espacial, M2 ingesta QField e informe de validación."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import numpy as np
import pytest

from algatech.contribuciones import ejecutar_contribuciones_monte_carlo
from algatech.deteccion import (
    agrupar_en_objetos_candidatos,
    calcular_indices_espectrales,
    entrenar_y_validar_rf_espacial,
)
from algatech.qfield import ingestar_fichas_qfield
from algatech.simulado import generar_gpkg_simulado
from algatech.validacion import evaluar_concordancia_expertos, generar_informe_validacion


def test_m1_indices_bloques_espaciales_y_objetos():
    rng = np.random.default_rng(7)
    b02 = rng.uniform(0.02, 0.12, (20, 20))
    b03 = rng.uniform(0.03, 0.15, (20, 20))
    b04 = rng.uniform(0.04, 0.25, (20, 20))
    b08 = rng.uniform(0.10, 0.45, (20, 20))
    b11 = rng.uniform(0.05, 0.30, (20, 20))
    idx = calcular_indices_espectrales(b02, b03, b04, b08, b11)
    assert set(idx.keys()) == {"ndvi", "mndwi", "bsi", "dndvi"}

    # Entrenamiento sintético de prueba unitaria para verificar GroupKFold espacial
    n = 60
    coords = np.column_stack([np.linspace(0, 1000, n), np.linspace(0, 1000, n)])
    X = rng.normal(size=(n, 5))
    y = (X[:, 0] > 0).astype(int)
    modelo, res = entrenar_y_validar_rf_espacial(X, y, coords)
    assert res.n_bloques >= 2
    assert 0.0 <= res.precision <= 1.0
    assert 0.0 <= res.exhaustividad <= 1.0
    assert modelo.n_features_in_ == 5

    # Agrupación en objetos: bloque 3x3 píxeles de 10m = 900 m2 (> 400 m2), pendiente 10° (< 25°)
    prob = np.zeros((10, 10))
    prob[2:5, 2:5] = 0.85
    pend = np.full((10, 10), 10.0)
    etiq, objs = agrupar_en_objetos_candidatos(prob, pend, tamano_pixel_m=10.0)
    assert len(objs) == 1
    assert objs[0]["area_m2"] == pytest.approx(900.0)
    assert etiq.max() == 1


def test_m2_ingesta_qfield_marca_reales(tmp_path: Path):
    gpkg_dst = tmp_path / "dst.gpkg"
    gpkg_qf = tmp_path / "qf.gpkg"
    generar_gpkg_simulado(ruta_salida=gpkg_dst)
    generar_gpkg_simulado(ruta_salida=gpkg_qf)

    res = ingestar_fichas_qfield(gpkg_dst, gpkg_qf)
    assert res["fichas_ingresadas"] == 6

    conn = sqlite3.connect(str(gpkg_dst))
    try:
        reales = conn.execute("SELECT COUNT(*) FROM fichas_campo WHERE sintetico = 0").fetchone()[0]
        assert reales == 6
    finally:
        conn.close()


def test_validacion_no_usa_sinteticos_y_kendall(tmp_path: Path):
    ruta = tmp_path / "sim.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta)
    ejecutar_contribuciones_monte_carlo(ruta)

    informe = generar_informe_validacion(ruta, ruta_salida_md=tmp_path / "val.md")
    txt = informe.read_text(encoding="utf-8")
    assert "PENDIENTE DE DATOS REALES" in txt

    conc = evaluar_concordancia_expertos(["A", "B", "C", "D", "E"], ["A", "C", "B", "D", "E"], top_k=5)
    assert conc["valido"] is True
    assert conc["traslape_top_k"] == 5
    assert conc["tau_kendall"] > 0.5
