"""Módulo M5: Semáforo de consumo de pescado por tramo y gremio trófico."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

import numpy as np

from algatech.config import cargar_configuracion


def normalizar_a_mg_kg_ph(
    valor: float,
    unidad: str = "mg/kg_ph",
    fraccion_humedad: float = 0.78,
) -> float:
    """Normaliza concentraciones de Hg a mg/kg peso húmedo (p.h.).

    Unidades soportadas:
    - 'mg/kg_ph', 'mg/kg', 'ppm', 'ug/g': equivalentes en peso húmedo.
    - 'ug/kg_ph', 'ppb': divide entre 1000.
    - 'mg/kg_ps' (peso seco): multiplica por (1 - fraccion_humedad).
    """
    if valor < 0:
        raise ValueError("La concentración de Hg no puede ser negativa.")
    u = unidad.strip().lower()
    if u in {"mg/kg_ph", "mg/kg", "ppm", "ug/g"}:
        return float(valor)
    if u in {"ug/kg_ph", "ug/kg", "ppb"}:
        return float(valor) / 1000.0
    if u in {"mg/kg_ps", "ppm_ps"}:
        if not (0.0 < fraccion_humedad < 1.0):
            raise ValueError("fraccion_humedad debe estar en (0, 1).")
        return float(valor) * (1.0 - fraccion_humedad)
    raise ValueError(f"Unidad de concentración no soportada: '{unidad}'")


def clasificar_color_semaforo(
    mediana_hg: float | None,
    umbral: float,
    cfg_semaforo: dict[str, Any],
) -> str:
    """Clasifica un tramo/gremio en verde, amarillo, rojo o gris (sin dato)."""
    if mediana_hg is None:
        return str(cfg_semaforo.get("etiqueta_sin_dato", "gris"))
    frac = float(mediana_hg) / float(umbral)
    if frac < float(cfg_semaforo["verde_max_fraccion"]):
        return "verde"
    if frac <= float(cfg_semaforo["amarillo_max_fraccion"]):
        return "amarillo"
    return "rojo"


def calcular_semaforo_pescado(
    ruta_gpkg: Path | str,
    config_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Calcula mediana, p90 y color por tramo y gremio, y actualiza `tramos_rio`."""
    cfg = cargar_configuracion(config_dir)
    umbrales = cfg.umbrales["umbrales_hg_mg_kg_ph"]
    cfg_sem = cfg.umbrales["semaforo"]

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        tramos = conn.execute(
            "SELECT tramo_id, nombre_rio, sintetico FROM tramos_rio ORDER BY tramo_id"
        ).fetchall()
        peces = conn.execute(
            "SELECT tramo_id, gremio_trofico, hg_mg_kg_ph, sintetico FROM peces_hg"
        ).fetchall()

        agrupado: dict[tuple[str, str], list[float]] = {}
        sint_por_tramo: dict[str, int] = {}
        for tid, gremio, hg, sint in peces:
            agrupado.setdefault((tid, gremio), []).append(float(hg))
            if int(sint) == 1:
                sint_por_tramo[tid] = 1

        resumen_tramos: list[dict[str, Any]] = []
        for tid, nombre_rio, t_sint in tramos:
            fila_res = {
                "tramo_id": tid,
                "nombre_rio": nombre_rio,
                "sintetico": int(t_sint) == 1 or sint_por_tramo.get(tid, 0) == 1,
            }
            tiene_datos = False
            for gremio in ("no_depredador", "depredador"):
                vals = agrupado.get((tid, gremio), [])
                umbral = float(umbrales.get(gremio, umbrales["defecto"]))
                if vals:
                    tiene_datos = True
                    arr = np.array(vals, dtype=float)
                    med = float(np.percentile(arr, 50))
                    p90 = float(np.percentile(arr, 90))
                    color = clasificar_color_semaforo(med, umbral, cfg_sem)
                else:
                    med = None
                    p90 = None
                    color = clasificar_color_semaforo(None, umbral, cfg_sem)

                fila_res[f"{gremio}_n"] = len(vals)
                fila_res[f"{gremio}_p50"] = med
                fila_res[f"{gremio}_p90"] = p90
                fila_res[f"semaforo_{gremio}"] = color

            evidencia = "medido" if tiene_datos else "sin_dato"
            fila_res["evidencia"] = evidencia
            resumen_tramos.append(fila_res)

            conn.execute(
                """
                UPDATE tramos_rio
                SET semaforo_no_depredador = ?,
                    semaforo_depredador = ?,
                    evidencia_semaforo = ?
                WHERE tramo_id = ?
                """,
                (
                    fila_res["semaforo_no_depredador"],
                    fila_res["semaforo_depredador"],
                    evidencia,
                    tid,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "mensaje_comunitario": cfg_sem["mensaje_comunitario"],
        "estado_umbrales": cfg.umbrales.get("estado_validacion", "SIN_ESTADO"),
        "tramos": resumen_tramos,
    }


def generar_comunicacion_comunitaria(
    ruta_gpkg: Path | str,
    carpeta_salida: Path | str | None = None,
    config_dir: Path | str | None = None,
) -> dict[str, Path]:
    """Genera tabla imprimible por comunidad y textos de 3 líneas para radio/WhatsApp."""
    res = calcular_semaforo_pescado(ruta_gpkg, config_dir)
    tramos_idx = {t["tramo_id"]: t for t in res["tramos"]}

    if carpeta_salida is None:
        carpeta_salida = Path(__file__).resolve().parents[2] / "data" / "processed"
    out_dir = Path(carpeta_salida)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        receptores = conn.execute(
            "SELECT receptor_id, nombre, tipo, tramo_id, sintetico FROM puntos_receptores ORDER BY receptor_id"
        ).fetchall()
    finally:
        conn.close()

    lineas_tabla = [
        "# Semáforo de consumo de pescado por comunidad",
        "",
        f"> **Recomendación:** {res['mensaje_comunitario']}",
        "",
        "| Comunidad / Punto | Tramo | No depredadores | Depredadores | Evidencia | Estado datos |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    lineas_radio = []

    for _rid, nombre, _tipo, tid, r_sint in receptores:
        t = tramos_idx[tid]
        es_sim = bool(r_sint) or t["sintetico"]
        etiqueta_sim = "DATOS SIMULADOS" if es_sim else "Medido"
        c_no = t["semaforo_no_depredador"].upper()
        c_dep = t["semaforo_depredador"].upper()

        lineas_tabla.append(
            f"| {nombre} | {t['nombre_rio']} | {c_no} | {c_dep} | {t['evidencia']} | {etiqueta_sim} |"
        )

        prefijo = "[DATOS SIMULADOS] " if es_sim else ""
        texto_3_lineas = (
            f"{prefijo}{nombre} ({t['nombre_rio']}): No depredadores en {c_no}, depredadores en {c_dep}.\n"
            f"Evidencia: {t['evidencia']}. Si está en GRIS, el tramo requiere muestreo.\n"
            f"{res['mensaje_comunitario']}"
        )
        lineas_radio.append(texto_3_lineas)

    ruta_tabla = out_dir / "semaforo_comunidades.md"
    ruta_radio = out_dir / "mensajes_radio_whatsapp.txt"
    ruta_tabla.write_text("\n".join(lineas_tabla) + "\n", encoding="utf-8")
    ruta_radio.write_text("\n\n---\n\n".join(lineas_radio) + "\n", encoding="utf-8")

    return {"tabla_md": ruta_tabla, "mensajes_txt": ruta_radio}
