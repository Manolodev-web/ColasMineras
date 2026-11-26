"""Módulo M4: Atribución probabilística aguas abajo con Monte Carlo (500 sorteos)."""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from algatech.config import ConfiguracionProyecto, cargar_configuracion
from algatech.hidrologia import ejecutar_hidrologia
from algatech.plugins import calcular_fuerza_fuente
from algatech.schema import decode_gpkg_geom


def _muestrear_parametro(rng: np.random.Generator, spec: dict[str, Any], n: int) -> np.ndarray:
    dist = str(spec.get("distribucion", "uniforme")).lower()
    vmin = float(spec["min"])
    vmax = float(spec["max"])
    if vmax < vmin:
        raise ValueError(f"Rango inválido en Monte Carlo: min={vmin} > max={vmax}")
    if dist == "uniforme":
        return rng.uniform(vmin, vmax, size=n)
    if dist == "lognormal":
        # Media geométrica y desviación para cubrir aproximadamente [vmin, vmax]
        mu = 0.5 * (math.log(vmin) + math.log(vmax))
        sigma = max(1e-6, (math.log(vmax) - math.log(vmin)) / 3.29)
        return np.clip(rng.lognormal(mean=mu, sigma=sigma, size=n), vmin, vmax)
    raise ValueError(f"Distribución Monte Carlo no soportada: {dist}")


def _factor_uso_hg(
    tipo_pasivo: str,
    indicio_declarativo: str | None,
    cfg_fuentes: dict[str, Any],
) -> float:
    cfg_tipo = cfg_fuentes[tipo_pasivo]
    if indicio_declarativo == "si":
        return float(cfg_tipo["factor_uso_hg_declarado_si"])
    if indicio_declarativo == "no":
        return float(cfg_tipo["factor_uso_hg_declarado_no"])
    return float(cfg_tipo["factor_uso_hg_defecto"])


def ejecutar_contribuciones_monte_carlo(
    ruta_gpkg: Path | str,
    config_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Calcula S_i, K_i, T_ij, C_ij, parte_ij e I_i con Monte Carlo y persiste en el GPKG."""
    cfg: ConfiguracionProyecto = cargar_configuracion(config_dir)
    mc_cfg = cfg.parametros["monte_carlo"]
    cfg_fuentes = cfg.parametros["fuentes"]

    n_sorteos = int(mc_cfg["n_sorteos"])
    semilla = int(mc_cfg["semilla"])
    top_k = int(mc_cfg["top_k"])
    umbral_estab = float(mc_cfg["umbral_estabilidad_top_k"])
    beta = float(mc_cfg["beta_agua_quieta"])

    hidro = ejecutar_hidrologia(ruta_gpkg)
    proy_colas = hidro["proy_colas"]
    matriz_L_km = hidro["matriz_L_km"]

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        colas_rows = conn.execute(
            """
            SELECT cola_id, tipo_pasivo, area_m2, altura_m, f_erosion, evidencia, sintetico
            FROM colas_candidatas
            ORDER BY cola_id
            """
        ).fetchall()

        fichas_rows = conn.execute(
            """
            SELECT cola_id, indicios_hg_declarativo, licencia_ambiental
            FROM fichas_campo
            """
        ).fetchall()

        rec_rows = conn.execute(
            """
            SELECT receptor_id, poblacion, consumo_kg_anio, agua_quieta, sintetico
            FROM puntos_receptores
            ORDER BY receptor_id
            """
        ).fetchall()
    finally:
        conn.close()

    if not colas_rows or not rec_rows:
        raise ValueError("Se requieren colas_candidatas y puntos_receptores para calcular contribuciones.")

    fichas_por_cola: dict[str, tuple[str, int]] = {}
    for cid, indicio, lic in fichas_rows:
        fichas_por_cola[cid] = (indicio, int(lic))

    n_colas = len(colas_rows)
    n_recs = len(rec_rows)

    cola_ids = [r[0] for r in colas_rows]
    rec_ids = [r[0] for r in rec_rows]

    S = np.zeros(n_colas, dtype=float)
    d_ladera = np.zeros(n_colas, dtype=float)
    f_erosion = np.zeros(n_colas, dtype=float)
    cola_sintetico = np.zeros(n_colas, dtype=int)
    cola_tipos = []

    for idx, (cid, tipo, area_m2, altura_m, f_er, _evid, sint) in enumerate(colas_rows):
        indicio = fichas_por_cola[cid][0] if cid in fichas_por_cola else None
        u_i = _factor_uso_hg(tipo, indicio, cfg_fuentes)
        S[idx] = calcular_fuerza_fuente(tipo, float(area_m2), altura_m, u_i, cfg_fuentes)
        d_ladera[idx] = proy_colas[cid].d_ladera_m
        f_erosion[idx] = float(f_er) if f_er is not None else 1.0
        cola_sintetico[idx] = int(sint)
        cola_tipos.append(tipo)

    w = np.zeros(n_recs, dtype=float)
    rec_sintetico = np.zeros(n_recs, dtype=int)
    for jdx, (_rid, pob, cons, agua_q, sint) in enumerate(rec_rows):
        w[jdx] = float(pob) * float(cons) * (1.0 + beta * float(agua_q))
        rec_sintetico[jdx] = int(sint)

    L_mat = np.full((n_colas, n_recs), np.inf, dtype=float)
    for idx, cid in enumerate(cola_ids):
        for jdx, rid in enumerate(rec_ids):
            L_mat[idx, jdx] = matriz_L_km[(cid, rid)]

    es_finito = np.isfinite(L_mat)

    rng = np.random.default_rng(semilla)
    D_samples = _muestrear_parametro(rng, mc_cfg["D_metros"], n_sorteos)
    lambda_samples = _muestrear_parametro(rng, mc_cfg["lambda_km"], n_sorteos)

    # Arreglos para almacenar los S sorteos
    C_all = np.zeros((n_sorteos, n_colas, n_recs), dtype=float)
    parte_all = np.zeros((n_sorteos, n_colas, n_recs), dtype=float)
    I_all = np.zeros((n_sorteos, n_colas), dtype=float)
    en_top_k = np.zeros((n_sorteos, n_colas), dtype=int)

    k_efectivo = min(top_k, n_colas)

    for s_idx in range(n_sorteos):
        D_val = D_samples[s_idx]
        lam_val = lambda_samples[s_idx]

        K = np.exp(-d_ladera / D_val) * f_erosion  # (n_colas,)
        T = np.zeros_like(L_mat)
        T[es_finito] = np.exp(-L_mat[es_finito] / lam_val)

        SK = S * K  # (n_colas,)
        C = SK[:, None] * T  # (n_colas, n_recs)

        suma_por_rec = C.sum(axis=0)  # (n_recs,)
        parte = np.zeros_like(C)
        mascara_pos = suma_por_rec > 0
        parte[:, mascara_pos] = C[:, mascara_pos] / suma_por_rec[None, mascara_pos]

        I_vec = SK * (T @ w)

        C_all[s_idx] = C
        parte_all[s_idx] = parte
        I_all[s_idx] = I_vec

        # Índices del top-k en este sorteo (mayor I_i)
        top_indices = np.argsort(I_vec)[::-1][:k_efectivo]
        en_top_k[s_idx, top_indices] = 1

    C_p50 = np.percentile(C_all, 50, axis=0)
    parte_p10 = np.percentile(parte_all, 10, axis=0)
    parte_p50 = np.percentile(parte_all, 50, axis=0)
    parte_p90 = np.percentile(parte_all, 90, axis=0)

    I_p10 = np.percentile(I_all, 10, axis=0)
    I_p50 = np.percentile(I_all, 50, axis=0)
    I_p90 = np.percentile(I_all, 90, axis=0)
    prob_top_k = en_top_k.mean(axis=0)

    # Guardar en GeoPackage (contribuciones + base de ranking que completará M6)
    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM contribuciones")
        cur.execute("DELETE FROM ranking")

        contrib_registros = []
        for idx, cid in enumerate(cola_ids):
            for jdx, rid in enumerate(rec_ids):
                dist_km = L_mat[idx, jdx]
                if not math.isfinite(dist_km):
                    continue
                sint = 1 if (cola_sintetico[idx] == 1 or rec_sintetico[jdx] == 1) else 0
                contrib_registros.append(
                    (
                        f"{cid}__{rid}",
                        cid,
                        rid,
                        float(dist_km),
                        float(parte_p50[idx, jdx]),
                        float(parte_p10[idx, jdx]),
                        float(parte_p90[idx, jdx]),
                        float(C_p50[idx, jdx]),
                        "estimado",
                        sint,
                    )
                )

        cur.executemany(
            """
            INSERT INTO contribuciones
            (contrib_id, cola_id, receptor_id, distancia_rio_km, parte_p50, parte_p10, parte_p90, c_ij_p50, evidencia, sintetico)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            contrib_registros,
        )

        # Normalizar I_p50 a [0, 1] como R_i preliminar hasta que M6 incorpore población y agua quieta
        max_I = float(I_p50.max()) if I_p50.max() > 0 else 1.0
        ranking_registros = []
        for idx, cid in enumerate(cola_ids):
            es_prio = 1 if prob_top_k[idx] >= umbral_estab else 0
            lic = fichas_por_cola[cid][1] if cid in fichas_por_cola else 0
            r_prelim = float(I_p50[idx] / max_I)
            ranking_registros.append(
                (
                    cid,
                    cola_tipos[idx],
                    float(I_p50[idx]),
                    float(I_p10[idx]),
                    float(I_p90[idx]),
                    float(prob_top_k[idx]),
                    es_prio,
                    r_prelim,
                    None,
                    1 if lic == 1 else 0,
                    "pendiente_m6",
                    es_prio,
                    "estimado",
                    int(cola_sintetico[idx]),
                )
            )

        cur.executemany(
            """
            INSERT INTO ranking
            (cola_id, tipo_pasivo, I_p50, I_p10, I_p90, prob_top_k, es_prioritaria, R_i,
             ley_equilibrio_g_t, reprocesable, cuadrante, prioridad_muestreo, evidencia, sintetico)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ranking_registros,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "n_sorteos": n_sorteos,
        "n_colas": n_colas,
        "n_receptores": n_recs,
        "cola_ids": cola_ids,
        "I_p50": I_p50,
        "prob_top_k": prob_top_k,
        "prioritarias": [cid for idx, cid in enumerate(cola_ids) if prob_top_k[idx] >= umbral_estab],
    }


def validar_spearman_peces(
    ruta_gpkg: Path | str,
    excluir_sinteticos: bool = True,
) -> dict[str, Any]:
    """Calcula la correlación de Spearman entre carga acumulada aguas arriba y Hg en peces.

    Estandariza Hg por gremio trófico (z-score) y compara frente a un modelo base
    de distancia mínima a la cola más cercana.
    """
    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        filtro = "WHERE sintetico = 0" if excluir_sinteticos else ""
        peces = conn.execute(
            f"SELECT tramo_id, gremio_trofico, hg_mg_kg_ph FROM peces_hg {filtro}"
        ).fetchall()
        tramos = conn.execute("SELECT tramo_id, geom FROM tramos_rio").fetchall()
        colas = conn.execute("SELECT cola_id, geom FROM colas_candidatas").fetchall()
        contribs = conn.execute(
            """
            SELECT r.tramo_id, SUM(c.c_ij_p50)
            FROM contribuciones c
            JOIN puntos_receptores r ON c.receptor_id = r.receptor_id
            GROUP BY r.tramo_id
            """
        ).fetchall()
    finally:
        conn.close()

    if len(peces) < 3:
        return {
            "valido": False,
            "motivo": "Insuficientes muestras reales de peces (se requieren >= 3 con sintetico=0)."
            if excluir_sinteticos
            else "Insuficientes muestras de peces.",
            "n_muestras": len(peces),
        }

    # Estandarización por gremio trófico
    por_gremio: dict[str, list[float]] = {}
    for _tid, gremio, hg in peces:
        por_gremio.setdefault(gremio, []).append(float(hg))

    stats_gremio = {}
    for gremio, vals in por_gremio.items():
        arr = np.array(vals, dtype=float)
        std = float(arr.std(ddof=0))
        stats_gremio[gremio] = (float(arr.mean()), std if std > 0 else 1.0)

    carga_por_tramo = {tid: float(val) for tid, val in contribs}
    tramo_geom = {tid: decode_gpkg_geom(blob) for tid, blob in tramos}
    cola_geoms = [decode_gpkg_geom(blob).centroid for _cid, blob in colas]

    hg_z = []
    cargas = []
    dist_min_base = []

    for tid, gremio, hg in peces:
        media, std = stats_gremio[gremio]
        hg_z.append((float(hg) - media) / std)
        cargas.append(carga_por_tramo.get(tid, 0.0))
        t_geom = tramo_geom[tid]
        dist_min_base.append(min(t_geom.distance(cg) for cg in cola_geoms) if cola_geoms else 0.0)

    rho_modelo, p_modelo = spearmanr(cargas, hg_z)
    # En modelo base de cercanía, menor distancia debería asociarse a mayor Hg (signo negativo)
    rho_base, p_base = spearmanr([-d for d in dist_min_base], hg_z)

    return {
        "valido": True,
        "n_muestras": len(peces),
        "excluir_sinteticos": excluir_sinteticos,
        "spearman_modelo": None if math.isnan(rho_modelo) else float(rho_modelo),
        "p_valor_modelo": None if math.isnan(p_modelo) else float(p_modelo),
        "spearman_base_distancia": None if math.isnan(rho_base) else float(rho_base),
        "p_valor_base": None if math.isnan(p_base) else float(p_base),
    }
