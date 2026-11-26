"""Módulo M6: Priorización multicriterio R_i, ley de equilibrio, cuadrantes y lista de muestreo."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import numpy as np

from algatech.config import cargar_configuracion


def _rango_percentil(valores: np.ndarray) -> np.ndarray:
    """Convierte un vector numérico a rango percentil en [0, 1]."""
    n = len(valores)
    if n == 0:
        return valores
    if n == 1 or np.allclose(valores, valores[0]):
        return np.ones(n, dtype=float)
    orden = np.argsort(valores, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[orden] = np.arange(n, dtype=float) / (n - 1)
    return ranks


def calcular_ley_equilibrio_g_t(
    area_m2: float,
    altura_m: float,
    cfg_econ: dict[str, Any],
) -> float | None:
    """Calcula la ley mínima de oro (g/t) donde el beneficio neto V_i = 0."""
    densidad = float(cfg_econ["densidad_cola_t_m3"])
    recup = float(cfg_econ["recuperacion_gravimetrica_fraccion"])
    precio = float(cfg_econ["precio_oro_usd_por_g"])
    costo_t = float(cfg_econ["costo_reproceso_usd_por_t"])
    capex = float(cfg_econ["capex_movilizacion_usd"])

    toneladas = float(area_m2) * float(altura_m) * densidad
    if toneladas <= 0 or recup <= 0 or precio <= 0:
        return None
    ingreso_por_g = recup * precio
    costo_total_por_t = costo_t + (capex / toneladas)
    return float(costo_total_por_t / ingreso_por_g)


def asignar_cuadrante(
    r_i: float,
    ley_eq_g_t: float | None,
    reprocesable: bool,
    cfg_cuad: dict[str, Any],
) -> str:
    """Asigna uno de los 4 cuadrantes de acción respetando la regla de licencia ambiental."""
    riesgo_alto = r_i >= float(cfg_cuad["umbral_riesgo_alto"])
    ley_favorable = (
        ley_eq_g_t is not None
        and ley_eq_g_t <= float(cfg_cuad["umbral_ley_equilibrio_favorable_g_t"])
    )

    if riesgo_alto and ley_favorable and reprocesable:
        return "remediar_y_reprocesar"
    if riesgo_alto:
        return "remediar_con_fondos_publicos"
    if (not riesgo_alto) and ley_favorable and reprocesable:
        return "reprocesar_solo_con_licencia"
    return "vigilar"


def calcular_ranking_y_cuadrantes(
    ruta_gpkg: Path | str,
    config_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Calcula R_i, ley de equilibrio, cuadrantes y lista 'dónde tomar muestras'."""
    cfg = cargar_configuracion(config_dir)
    w_cfg = cfg.pesos["riesgo"]
    econ_cfg = cfg.pesos["economia_referencia"]
    cuad_cfg = cfg.pesos["cuadrantes"]
    fuentes_cfg = cfg.parametros["fuentes"]
    top_k = int(cfg.parametros["monte_carlo"]["top_k"])

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        rows = conn.execute(
            """
            SELECT r.cola_id, r.tipo_pasivo, r.I_p50, r.I_p10, r.I_p90, r.prob_top_k,
                   r.es_prioritaria, r.evidencia, r.sintetico,
                   c.area_m2, c.altura_m
            FROM ranking r
            JOIN colas_candidatas c ON r.cola_id = c.cola_id
            ORDER BY r.cola_id
            """
        ).fetchall()

        if not rows:
            raise ValueError("La tabla ranking está vacía; ejecute primero M4 (contribuciones).")

        fichas = conn.execute(
            "SELECT cola_id, licencia_ambiental FROM fichas_campo"
        ).fetchall()
        licencia_por_cola = {cid: int(lic) == 1 for cid, lic in fichas}

        receptores_por_cola = conn.execute(
            """
            SELECT c.cola_id, SUM(p.poblacion), MAX(p.agua_quieta)
            FROM contribuciones c
            JOIN puntos_receptores p ON c.receptor_id = p.receptor_id
            GROUP BY c.cola_id
            """
        ).fetchall()
        pob_y_agua = {
            cid: (float(pob or 0.0), float(aq or 0.0))
            for cid, pob, aq in receptores_por_cola
        }

        n = len(rows)
        i_vec = np.array([float(r[2]) for r in rows], dtype=float)
        pob_vec = np.array([pob_y_agua.get(r[0], (0.0, 0.0))[0] for r in rows], dtype=float)
        aq_vec = np.array([pob_y_agua.get(r[0], (0.0, 0.0))[1] for r in rows], dtype=float)

        pct_i = _rango_percentil(i_vec)
        pct_pob = _rango_percentil(pob_vec)
        pct_aq = _rango_percentil(aq_vec)

        w_i = float(w_cfg["peso_impacto_I"])
        w_p = float(w_cfg["peso_poblacion_aguas_abajo"])
        w_a = float(w_cfg["peso_agua_quieta"])

        R_vec = w_i * pct_i + w_p * pct_pob + w_a * pct_aq

        resultados = []
        for idx, row in enumerate(rows):
            cid = row[0]
            tipo = row[1]
            area_m2 = float(row[9])
            alt_m = float(row[10]) if row[10] is not None else float(fuentes_cfg[tipo]["altura_defecto_m"])

            r_val = float(np.clip(R_vec[idx], 0.0, 1.0))
            ley_eq = calcular_ley_equilibrio_g_t(area_m2, alt_m, econ_cfg)
            reproc = licencia_por_cola.get(cid, False)
            cuadrante = asignar_cuadrante(r_val, ley_eq, reproc, cuad_cfg)

            resultados.append(
                {
                    "cola_id": cid,
                    "tipo_pasivo": tipo,
                    "R_i": r_val,
                    "I_p50": float(row[2]),
                    "prob_top_k": float(row[5]),
                    "es_prioritaria": int(row[6]) == 1,
                    "ley_equilibrio_g_t": ley_eq,
                    "reprocesable": reproc,
                    "cuadrante": cuadrante,
                    "sintetico": int(row[8]) == 1,
                }
            )

        # Ordenar por R_i descendente (y cola_id ascendente para desempate determinista)
        resultados.sort(key=lambda d: (-d["R_i"], d["cola_id"]))

        top_ids = {d["cola_id"] for d in resultados[: min(top_k, len(resultados))]}
        # 2 sitios de control: los de menor R_i que no estén en el top-k
        no_top = [d for d in reversed(resultados) if d["cola_id"] not in top_ids]
        controles_ids = {d["cola_id"] for d in no_top[:2]}
        muestreo_ids = top_ids | controles_ids

        for d in resultados:
            d["prioridad_muestreo"] = d["cola_id"] in muestreo_ids
            d["rol_muestreo"] = (
                "prioritario"
                if d["cola_id"] in top_ids
                else ("control" if d["cola_id"] in controles_ids else "no_seleccionado")
            )
            conn.execute(
                """
                UPDATE ranking
                SET R_i = ?,
                    ley_equilibrio_g_t = ?,
                    reprocesable = ?,
                    cuadrante = ?,
                    prioridad_muestreo = ?
                WHERE cola_id = ?
                """,
                (
                    d["R_i"],
                    d["ley_equilibrio_g_t"],
                    1 if d["reprocesable"] else 0,
                    d["cuadrante"],
                    1 if d["prioridad_muestreo"] else 0,
                    d["cola_id"],
                ),
            )
        conn.commit()
    finally:
        conn.close()

    lista_muestreo = [d for d in resultados if d["prioridad_muestreo"]]
    return {
        "ranking": resultados,
        "donde_muestrear": lista_muestreo,
        "n_prioritarios": len(top_ids),
        "n_controles": len(controles_ids),
    }
