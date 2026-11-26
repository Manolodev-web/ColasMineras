"""Pruebas de Fase 1: M3 hidrología (grafo, Dijkstra L_ij) y M4 contribuciones Monte Carlo."""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3

import pytest

from algatech.contribuciones import (
    ejecutar_contribuciones_monte_carlo,
    validar_spearman_peces,
)
from algatech.hidrologia import (
    construir_grafo_hidrologico,
    distancia_aguas_abajo_km,
    ejecutar_hidrologia,
)
from algatech.simulado import generar_gpkg_simulado


def test_grafo_y_distancias_aguas_abajo(tmp_path: Path):
    ruta = tmp_path / "sim.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta)

    res = ejecutar_hidrologia(ruta)
    grafo = res["grafo"]
    tramos_info = res["tramos_info"]
    proy_colas = res["proy_colas"]
    proy_rec = res["proy_receptores"]

    assert grafo.number_of_nodes() == 5
    # COLA-03 está en T-02 (Mapiri); REC-01 está en T-01 (Tipuani). No está aguas abajo -> inf
    l_invalido = distancia_aguas_abajo_km(grafo, tramos_info, proy_colas["COLA-03"], proy_rec["REC-01"])
    assert math.isinf(l_invalido)

    # COLA-01 está en T-01 (frac ~0.25); REC-04 está en T-05 (frac ~0.70)
    # Debe ser finita y mayor que la suma de tramos intermedios T-03 (22 km) + T-04 (27 km)
    l_valido = distancia_aguas_abajo_km(grafo, tramos_info, proy_colas["COLA-01"], proy_rec["REC-04"])
    assert math.isfinite(l_valido)
    assert l_valido > (22.0 + 27.0)


def test_monte_carlo_reproducible_y_partes_suman_uno(tmp_path: Path):
    ruta1 = tmp_path / "sim1.gpkg"
    ruta2 = tmp_path / "sim2.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta1)
    generar_gpkg_simulado(ruta_salida=ruta2)

    r1 = ejecutar_contribuciones_monte_carlo(ruta1)
    r2 = ejecutar_contribuciones_monte_carlo(ruta2)

    assert r1["n_sorteos"] == 500
    assert list(r1["I_p50"]) == pytest.approx(list(r2["I_p50"]))
    assert list(r1["prob_top_k"]) == pytest.approx(list(r2["prob_top_k"]))

    # Verificar que los percentiles cumplen p10 <= p50 <= p90 y sintetico=1
    conn = sqlite3.connect(str(ruta1))
    try:
        filas = conn.execute(
            "SELECT receptor_id, parte_p10, parte_p50, parte_p90, sintetico FROM contribuciones"
        ).fetchall()
        assert len(filas) > 0
        for _rid, p10, p50, p90, sint in filas:
            assert 0.0 <= p10 <= p50 <= p90 <= 1.0 + 1e-9
            assert sint == 1

        # Verificar que validar_spearman_peces rechaza datos sintéticos por defecto
        val = validar_spearman_peces(ruta1, excluir_sinteticos=True)
        assert val["valido"] is False
        assert val["n_muestras"] == 0
    finally:
        conn.close()
