"""Generador del informe de validación científica (excluye datos sintéticos de métricas)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
from scipy.stats import kendalltau

from algatech.contribuciones import validar_spearman_peces
from algatech.deteccion import ResultadoValidacionM1


def evaluar_concordancia_expertos(
    ranking_modelo: list[str],
    ranking_experto: list[str],
    top_k: int = 5,
) -> dict[str, Any]:
    """Calcula tau de Kendall y traslape top-k entre el ranking del modelo y juicio experto."""
    comunes = [cid for cid in ranking_modelo if cid in set(ranking_experto)]
    if len(comunes) < 2:
        return {"valido": False, "motivo": "Se requieren al menos 2 sitios comunes."}

    pos_mod = {cid: i for i, cid in enumerate(ranking_modelo)}
    pos_exp = {cid: i for i, cid in enumerate(ranking_experto)}
    r_mod = [pos_mod[c] for c in comunes]
    r_exp = [pos_exp[c] for c in comunes]

    tau, p_val = kendalltau(r_mod, r_exp)
    top_mod = set(ranking_modelo[:top_k])
    top_exp = set(ranking_experto[:top_k])
    traslape = len(top_mod & top_exp)

    return {
        "valido": True,
        "tau_kendall": float(tau),
        "p_valor": float(p_val),
        "traslape_top_k": traslape,
        "k": top_k,
    }


def generar_informe_validacion(
    ruta_gpkg: Path | str,
    ruta_salida_md: Path | str | None = None,
    resultado_m1: ResultadoValidacionM1 | None = None,
    ranking_experto: list[str] | None = None,
) -> Path:
    """Genera `docs/informe_validacion.md` reportando métricas reales o vacíos de datos."""
    if ruta_salida_md is None:
        ruta_salida_md = Path(__file__).resolve().parents[2] / "docs" / "informe_validacion.md"
    out = Path(ruta_salida_md)
    out.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        minutos_reales = [
            float(r[0])
            for r in conn.execute(
                "SELECT minutos_llenado FROM fichas_campo WHERE sintetico = 0 AND minutos_llenado IS NOT NULL"
            ).fetchall()
        ]
        ranking_real = [
            r[0]
            for r in conn.execute(
                "SELECT cola_id FROM ranking WHERE sintetico = 0 ORDER BY R_i DESC, cola_id"
            ).fetchall()
        ]
        sensibilidad_rows = conn.execute(
            "SELECT I_p10, I_p50, I_p90, prob_top_k, sintetico FROM ranking"
        ).fetchall()
    finally:
        conn.close()

    spearman_res = validar_spearman_peces(ruta_gpkg, excluir_sinteticos=True)

    lineas = [
        "# Informe de Validación Científica — AlgaTech (ORO-4.2)",
        "",
        "> **Principio de honestidad científica:** Ningún dato marcado con `sintetico=1` se utiliza en las métricas de validación. Cuando faltan datos reales, se declara explícitamente.",
        "",
        "## 1. Detección satelital (M1 — bloques espaciales)",
    ]

    if resultado_m1 is not None:
        lineas.extend(
            [
                f"- **Precisión (CV bloques espaciales):** {resultado_m1.precision:.3f}",
                f"- **Exhaustividad / Recall:** {resultado_m1.exhaustividad:.3f}",
                f"- **Bloques espaciales:** {resultado_m1.n_bloques} | **Muestras reales:** {resultado_m1.n_muestras_reales}",
            ]
        )
    else:
        lineas.append("- **Estado:** PENDIENTE DE DATOS REALES (requiere polígonos de etiquetas en campo).")

    lineas.extend(["", "## 2. Eficiencia de ficha de campo (M2 — meta < 8 min)"])
    if minutos_reales:
        med_min = float(np.median(minutos_reales))
        lineas.append(f"- **Mediana observada:** {med_min:.2f} min/ficha (n = {len(minutos_reales)} fichas reales).")
    else:
        lineas.append("- **Estado:** PENDIENTE DE DATOS REALES (0 fichas con `sintetico=0`).")

    lineas.extend(["", "## 3. Concordancia del ranking con juicio de expertos"])
    if ranking_experto and ranking_real:
        conc = evaluar_concordancia_expertos(ranking_real, ranking_experto, top_k=5)
        if conc["valido"]:
            lineas.append(
                f"- **Tau de Kendall:** {conc['tau_kendall']:.3f} (p={conc['p_valor']:.4f}) | "
                f"**Traslape top-{conc['k']}:** {conc['traslape_top_k']}/{conc['k']}"
            )
        else:
            lineas.append(f"- **Estado:** {conc['motivo']}")
    else:
        lineas.append("- **Estado:** PENDIENTE DE DATOS REALES (requiere ordenamiento de expertos sobre sitios reales).")

    lineas.extend(["", "## 4. Correlación con Hg en peces (`peces_hg`, Spearman por gremio)"])
    if spearman_res["valido"]:
        rho_m = spearman_res["spearman_modelo"]
        p_m = spearman_res["p_valor_modelo"]
        rho_b = spearman_res["spearman_base_distancia"]
        if rho_m is None or rho_b is None:
            lineas.append(
                f"- **Estado:** No calculable (todas las muestras reales [n={spearman_res['n_muestras']}] pertenecen a un único tramo)."
            )
        else:
            lineas.extend(
                [
                    f"- **Spearman modelo hidrológico:** {rho_m:.3f} (p={p_m:.4f})",
                    f"- **Spearman modelo base (distancia a mina más cercana):** {rho_b:.3f}",
                    f"- **Muestras reales usadas:** {spearman_res['n_muestras']}",
                ]
            )
    else:
        lineas.append(f"- **Estado:** {spearman_res['motivo']} (n_reales={spearman_res['n_muestras']}).")

    lineas.extend(["", "## 5. Análisis de sensibilidad Monte Carlo (500 sorteos)"])
    if sensibilidad_rows:
        ratios = [
            (r[2] - r[0]) / r[1] if r[1] > 0 else 0.0
            for r in sensibilidad_rows
        ]
        estables = sum(1 for r in sensibilidad_rows if r[3] >= 0.80)
        hay_sim = any(int(r[4]) == 1 for r in sensibilidad_rows)
        etiqueta = " *(sobre corrida actual con datos simulados)*" if hay_sim else ""
        lineas.extend(
            [
                f"- **Amplitud relativa mediana (p90 - p10) / p50:** {float(np.median(ratios)):.2f}{etiqueta}",
                f"- **Colas con estabilidad >= 80% en top-k:** {estables} de {len(sensibilidad_rows)}",
            ]
        )
    else:
        lineas.append("- Sin resultados de Monte Carlo en el GeoPackage.")

    out.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return out
