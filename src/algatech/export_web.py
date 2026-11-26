"""Exportador de la capa pública (GeoJSON/JSON) para la web estática sin servidores.

Regla de privacidad: nunca exporta `responsable_privado`, `consentimiento`,
`foto_ruta` ni coordenadas finas de `fichas_campo`.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
from typing import Any

import numpy as np
from shapely.geometry import mapping

from algatech import SCHEMA_VERSION
from algatech.config import cargar_configuracion
from algatech.ranking import _rango_percentil
from algatech.schema import decode_gpkg_geom


def utm19s_a_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convierte coordenadas UTM Zona 19S (EPSG:32719) a WGS84 (lon, lat)."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    k0 = 0.9996
    lon0 = math.radians(-69.0)

    x = easting - 500000.0
    y = northing - 10000000.0

    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)

    n1 = a / math.sqrt(1 - e2 * sin_phi1**2)
    t1 = tan_phi1**2
    c1 = ep2 * cos_phi1**2
    r1 = a * (1 - e2) / ((1 - e2 * sin_phi1**2) ** 1.5)
    d = x / (n1 * k0)

    lat = phi1 - (n1 * tan_phi1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / cos_phi1

    return math.degrees(lon), math.degrees(lat)


def _reproyectar_geojson_geom(geom_obj: dict[str, Any]) -> dict[str, Any]:
    """Reproyecta recursivamente un dict GeoJSON de UTM 19S a WGS84."""
    gtype = geom_obj["type"]
    coords = geom_obj["coordinates"]

    def conv_pt(pt):
        lon, lat = utm19s_a_wgs84(float(pt[0]), float(pt[1]))
        return [round(lon, 6), round(lat, 6)]

    if gtype == "Point":
        return {"type": "Point", "coordinates": conv_pt(coords)}
    if gtype == "LineString":
        return {"type": "LineString", "coordinates": [conv_pt(p) for p in coords]}
    if gtype == "Polygon":
        return {"type": "Polygon", "coordinates": [[conv_pt(p) for p in ring] for ring in coords]}
    raise ValueError(f"Tipo de geometría no soportado en exportador web: {gtype}")


def exportar_capa_publica_web(
    ruta_gpkg: Path | str,
    carpeta_web_data: Path | str | None = None,
    config_dir: Path | str | None = None,
) -> Path:
    """Exporta `datos_publicos.json` para la web estática (solo capa pública)."""
    cfg = cargar_configuracion(config_dir)
    if carpeta_web_data is None:
        carpeta_web_data = Path(__file__).resolve().parents[2] / "web" / "data"
    out_dir = Path(carpeta_web_data)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        colas_rows = conn.execute(
            """
            SELECT c.cola_id, c.geom, c.tipo_pasivo, c.area_m2, c.altura_m,
                   c.pendiente_media_deg, c.hand_m, c.en_cuadricula_minera,
                   c.evidencia, c.sintetico,
                   r.I_p50, r.I_p10, r.I_p90, r.prob_top_k, r.es_prioritaria,
                   r.R_i, r.ley_equilibrio_g_t, r.reprocesable, r.cuadrante, r.prioridad_muestreo,
                   COALESCE(d.fuente, 'Deteccion_M1')
            FROM colas_candidatas c
            JOIN ranking r ON c.cola_id = r.cola_id
            LEFT JOIN derechos_mineros d ON d.codigo_ajam = c.cola_id
            ORDER BY r.R_i DESC, c.cola_id
            """
        ).fetchall()

        tramos_rows = conn.execute(
            """
            SELECT tramo_id, geom, nombre_rio, orden_strahler, longitud_km,
                   semaforo_no_depredador, semaforo_depredador, evidencia_semaforo, sintetico
            FROM tramos_rio
            ORDER BY tramo_id
            """
        ).fetchall()

        rec_rows = conn.execute(
            """
            SELECT receptor_id, geom, nombre, tipo, tramo_id, poblacion, consumo_kg_anio, agua_quieta, sintetico
            FROM puntos_receptores
            ORDER BY receptor_id
            """
        ).fetchall()

        contrib_rows = conn.execute(
            """
            SELECT cola_id, receptor_id, distancia_rio_km, parte_p50, parte_p10, parte_p90, c_ij_p50, sintetico
            FROM contribuciones
            ORDER BY receptor_id, parte_p50 DESC
            """
        ).fetchall()

        pob_agua_rows = conn.execute(
            """
            SELECT c.cola_id, SUM(p.poblacion), MAX(p.agua_quieta)
            FROM contribuciones c
            JOIN puntos_receptores p ON c.receptor_id = p.receptor_id
            GROUP BY c.cola_id
            """
        ).fetchall()

        peces_rows = conn.execute(
            """
            SELECT muestra_id, tramo_id, especie, gremio_trofico, hg_mg_kg_ph, cita, metodo_analitico, calidad, sintetico
            FROM peces_hg
            ORDER BY hg_mg_kg_ph ASC
            """
        ).fetchall()
    finally:
        conn.close()

    pob_agua_map = {cid: (float(pob or 0.0), float(aq or 0.0)) for cid, pob, aq in pob_agua_rows}

    i_arr = np.array([float(r[10]) for r in colas_rows], dtype=float)
    pob_arr = np.array([pob_agua_map.get(r[0], (0.0, 0.0))[0] for r in colas_rows], dtype=float)
    aq_arr = np.array([pob_agua_map.get(r[0], (0.0, 0.0))[1] for r in colas_rows], dtype=float)

    pct_i = _rango_percentil(i_arr)
    pct_pob = _rango_percentil(pob_arr)
    pct_aq = _rango_percentil(aq_arr)

    contiene_simulados = False
    colas_features = []
    for idx, r in enumerate(colas_rows):
        es_sim = int(r[9]) == 1
        contiene_simulados = contiene_simulados or es_sim
        geom = decode_gpkg_geom(r[1])
        # Centroide aproximado en WGS84 para marcador y polígono generalizado
        geom_wgs = _reproyectar_geojson_geom(mapping(geom))
        lon_c, lat_c = utm19s_a_wgs84(geom.centroid.x, geom.centroid.y)
        pob_val, aq_val = pob_agua_map.get(r[0], (0.0, 0.0))

        colas_features.append(
            {
                "type": "Feature",
                "geometry": geom_wgs,
                "properties": {
                    "cola_id": r[0],
                    "centroide_wgs84": [round(lat_c, 6), round(lon_c, 6)],
                    "tipo_pasivo": r[2],
                    "area_m2": round(float(r[3]), 1),
                    "altura_m": None if r[4] is None else round(float(r[4]), 2),
                    "pendiente_media_deg": r[5],
                    "hand_m": r[6],
                    "en_cuadricula_minera": int(r[7]) == 1,
                    "evidencia": r[8],
                    "sintetico": es_sim,
                    "I_p50": round(float(r[10]), 3),
                    "I_p10": round(float(r[11]), 3),
                    "I_p90": round(float(r[12]), 3),
                    "prob_top_k": round(float(r[13]), 3),
                    "es_prioritaria": int(r[14]) == 1,
                    "R_i": round(float(r[15]), 4),
                    "pct_I": round(float(pct_i[idx]), 4),
                    "pct_poblacion": round(float(pct_pob[idx]), 4),
                    "pct_agua_quieta": round(float(pct_aq[idx]), 4),
                    "poblacion_aguas_abajo": int(pob_val),
                    "agua_quieta_aguas_abajo": round(aq_val, 2),
                    "ley_equilibrio_g_t": None if r[16] is None else round(float(r[16]), 3),
                    "reprocesable": int(r[17]) == 1,
                    "cuadrante": r[18],
                    "prioridad_muestreo": int(r[19]) == 1,
                    "fuente_poligono": r[20],
                    "ficha_pdf": f"fichas/{r[0]}.pdf",
                },
            }
        )

    tramos_features = []
    for tid, geom_blob, nombre, orden, long_km, sem_nd, sem_d, evid, sint in tramos_rows:
        es_sim = int(sint) == 1
        contiene_simulados = contiene_simulados or es_sim
        geom_wgs = _reproyectar_geojson_geom(mapping(decode_gpkg_geom(geom_blob)))
        tramos_features.append(
            {
                "type": "Feature",
                "geometry": geom_wgs,
                "properties": {
                    "tramo_id": tid,
                    "nombre_rio": nombre,
                    "orden_strahler": orden,
                    "longitud_km": round(float(long_km), 2),
                    "semaforo_no_depredador": sem_nd,
                    "semaforo_depredador": sem_d,
                    "evidencia_semaforo": evid,
                    "sintetico": es_sim,
                },
            }
        )

    top3_por_receptor: dict[str, list[dict[str, Any]]] = {}
    for cid, rid, dist_km, p50, p10, p90, _c50, sint in contrib_rows:
        contiene_simulados = contiene_simulados or (int(sint) == 1)
        lista = top3_por_receptor.setdefault(rid, [])
        if len(lista) < 3:
            lista.append(
                {
                    "cola_id": cid,
                    "distancia_rio_km": round(float(dist_km), 2),
                    "parte_p50": round(float(p50), 4),
                    "parte_p10": round(float(p10), 4),
                    "parte_p90": round(float(p90), 4),
                }
            )

    receptores_features = []
    for rid, geom_blob, nombre, tipo, tid, pob, cons, aq, sint in rec_rows:
        es_sim = int(sint) == 1
        contiene_simulados = contiene_simulados or es_sim
        geom_wgs = _reproyectar_geojson_geom(mapping(decode_gpkg_geom(geom_blob)))
        receptores_features.append(
            {
                "type": "Feature",
                "geometry": geom_wgs,
                "properties": {
                    "receptor_id": rid,
                    "nombre": nombre,
                    "tipo": tipo,
                    "tramo_id": tid,
                    "poblacion": int(pob),
                    "consumo_kg_anio": float(cons),
                    "agua_quieta": float(aq),
                    "top_3_colas": top3_por_receptor.get(rid, []),
                    "sintetico": es_sim,
                },
            }
        )

    peces_lista = [
        {
            "muestra_id": m[0],
            "tramo_id": m[1],
            "especie": m[2],
            "gremio_trofico": m[3],
            "hg_mg_kg_ph": round(float(m[4]), 3),
            "cita": m[5],
            "metodo_analitico": m[6],
            "calidad": m[7],
            "sintetico": int(m[8]) == 1,
        }
        for m in peces_rows
    ]

    payload = {
        "metadata": {
            "schema_version": SCHEMA_VERSION,
            "zona_nombre": cfg.zona["nombre"],
            "contiene_datos_simulados": contiene_simulados,
            "mensaje_comunitario": cfg.umbrales["semaforo"]["mensaje_comunitario"],
            "estado_umbrales": cfg.umbrales.get("estado_validacion", "PENDIENTE"),
            "pesos_defecto": cfg.pesos["riesgo"],
            "cuadrantes_cfg": cfg.pesos["cuadrantes"],
        },
        "colas": {"type": "FeatureCollection", "features": colas_features},
        "tramos": {"type": "FeatureCollection", "features": tramos_features},
        "receptores": {"type": "FeatureCollection", "features": receptores_features},
        "peces_hg": peces_lista,
    }

    ruta_json = out_dir / "datos_publicos.json"
    ruta_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Exportar resumen nacional de Bolivia si existe global_mining_polygons_v2.gpkg
    ruta_gmp = Path(__file__).resolve().parents[2] / "data" / "raw" / "global_mining_polygons_v2.gpkg"
    if ruta_gmp.exists():
        _exportar_resumen_bolivia(ruta_gmp, out_dir / "bolivia_mineria_resumen.json")

    return ruta_json


def _exportar_resumen_bolivia(ruta_gmp: Path, ruta_salida: Path) -> None:
    """Exporta centroides y área de polígonos mineros reales de toda Bolivia (GMP v2)."""
    conn = sqlite3.connect(str(ruta_gmp))
    try:
        tabla = conn.execute(
            "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'"
        ).fetchone()[0]
        rows = conn.execute(f'SELECT AREA, geom FROM "{tabla}" WHERE ISO3_CODE = ?', ("BOL",)).fetchall()
    finally:
        conn.close()

    puntos = []
    for idx, (area_km2, blob) in enumerate(rows, start=1):
        geom = decode_gpkg_geom(blob)
        if geom is None:
            continue
        c = geom.centroid
        puntos.append(
            {
                "id": f"BOL-{idx:04d}",
                "lat": round(float(c.y), 4),
                "lon": round(float(c.x), 4),
                "area_km2": round(float(area_km2 or 0.0), 4),
            }
        )
    ruta_salida.write_text(
        json.dumps({"fuente": "Global Mining Polygons v2 (BOL)", "total": len(puntos), "puntos": puntos}),
        encoding="utf-8",
    )
