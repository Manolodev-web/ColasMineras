"""Pruebas de Fase 2: M5 semáforo de pescado y M6 priorización / ley de equilibrio."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from algatech.config import cargar_configuracion
from algatech.contribuciones import ejecutar_contribuciones_monte_carlo
from algatech.ranking import asignar_cuadrante, calcular_ley_equilibrio_g_t, calcular_ranking_y_cuadrantes
from algatech.semaforo import (
    calcular_semaforo_pescado,
    clasificar_color_semaforo,
    generar_comunicacion_comunitaria,
    normalizar_a_mg_kg_ph,
)
from algatech.simulado import generar_gpkg_simulado


def test_normalizacion_peces_y_colores():
    assert normalizar_a_mg_kg_ph(0.5, "mg/kg_ph") == pytest.approx(0.5)
    assert normalizar_a_mg_kg_ph(500.0, "ppb") == pytest.approx(0.5)
    assert normalizar_a_mg_kg_ph(1.0, "mg/kg_ps", fraccion_humedad=0.80) == pytest.approx(0.2)

    cfg = cargar_configuracion()
    sem = cfg.umbrales["semaforo"]
    assert clasificar_color_semaforo(None, 0.5, sem) == "gris"
    assert clasificar_color_semaforo(0.20, 0.5, sem) == "verde"
    assert clasificar_color_semaforo(0.35, 0.5, sem) == "amarillo"
    assert clasificar_color_semaforo(0.65, 0.5, sem) == "rojo"


def test_semaforo_y_comunicacion_sobre_simulado(tmp_path: Path):
    ruta = tmp_path / "sim.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta)

    res = calcular_semaforo_pescado(ruta)
    por_tramo = {t["tramo_id"]: t for t in res["tramos"]}

    # T-01 y T-05 no tienen muestras -> deben quedar en gris y sin_dato
    assert por_tramo["T-01"]["semaforo_no_depredador"] == "gris"
    assert por_tramo["T-01"]["evidencia"] == "sin_dato"
    assert por_tramo["T-05"]["semaforo_depredador"] == "gris"

    # T-04 tiene Sábalo 0.62 y Pacú 0.48 -> mediana 0.55 > 0.5 -> rojo
    assert por_tramo["T-04"]["semaforo_no_depredador"] == "rojo"
    assert por_tramo["T-04"]["evidencia"] == "medido"

    archivos = generar_comunicacion_comunitaria(ruta, carpeta_salida=tmp_path / "out")
    txt = archivos["mensajes_txt"].read_text(encoding="utf-8")
    assert "DATOS SIMULADOS" in txt
    assert "no dejar de comer pescado" in txt.lower()


def test_ranking_reproducibilidad_y_licencia(tmp_path: Path):
    ruta = tmp_path / "sim.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta)
    ejecutar_contribuciones_monte_carlo(ruta)

    r1 = calcular_ranking_y_cuadrantes(ruta)
    r2 = calcular_ranking_y_cuadrantes(ruta)

    ids1 = [d["cola_id"] for d in r1["ranking"]]
    ids2 = [d["cola_id"] for d in r2["ranking"]]
    assert ids1 == ids2

    # Lista de muestreo = top_k (5) + 2 controles = 7
    assert r1["n_prioritarios"] == 5
    assert r1["n_controles"] == 2
    assert len(r1["donde_muestrear"]) == 7

    # Verificar regla estricta: reprocesable=True SOLO si tiene licencia_ambiental=1
    conn = sqlite3.connect(str(ruta))
    try:
        lics = {
            cid: int(lic) == 1
            for cid, lic in conn.execute("SELECT cola_id, licencia_ambiental FROM fichas_campo").fetchall()
        }
    finally:
        conn.close()

    for item in r1["ranking"]:
        if item["reprocesable"]:
            assert lics.get(item["cola_id"], False) is True
        if not lics.get(item["cola_id"], False):
            assert item["cuadrante"] not in {"remediar_y_reprocesar", "reprocesar_solo_con_licencia"}

    # Ley de equilibrio positiva y finita
    cfg = cargar_configuracion()
    ley = calcular_ley_equilibrio_g_t(10000.0, 2.0, cfg.pesos["economia_referencia"])
    assert ley is not None and ley > 0
