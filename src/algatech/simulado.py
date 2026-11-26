"""Generador reproducible de datos SIMULADOS (sintetico=1) para demostración y pruebas.

ADVERTENCIA: Todos los registros generados por este módulo son sintéticos y llevan
la bandera `sintetico=1`. Nunca deben emplearse en métricas de validación.
"""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from algatech.config import cargar_configuracion
from algatech.schema import crear_esquema_geopackage, encode_gpkg_geom


def wgs84_a_utm19s(lon_deg: float, lat_deg: float) -> tuple[float, float]:
    """Convierte coordenadas geográficas WGS84 a UTM Zona 19S (EPSG:32719)."""
    a = 6378137.0
    f = 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    lon0 = math.radians(-69.0)  # Meridiano central zona 19

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    n = a / math.sqrt(1 - e2 * sin_lat**2)
    t = tan_lat**2
    c = ep2 * cos_lat**2
    aa = cos_lat * (lon - lon0)

    m = a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * lat
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * lat)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * lat)
        - (35 * e2**3 / 3072) * math.sin(6 * lat)
    )

    easting = 500000.0 + k0 * n * (
        aa
        + (1 - t + c) * aa**3 / 6
        + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120
    )
    northing = 10000000.0 + k0 * (
        m
        + n
        * tan_lat
        * (
            aa**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720
        )
    )
    return easting, northing


def generar_gpkg_simulado(
    ruta_salida: Path | str | None = None,
    config_dir: Path | str | None = None,
    semilla: int = 42,
) -> Path:
    """Genera el GeoPackage de demostración con datos sintéticos marcados (`sintetico=1`)."""
    cfg = cargar_configuracion(config_dir)
    srid = cfg.epsg_proyecto
    bbox = cfg.zona["bbox_wgs84"]

    if ruta_salida is None:
        ruta_salida = Path(__file__).resolve().parents[2] / "data" / "simulado" / "algatech_simulado.gpkg"
    ruta = crear_esquema_geopackage(ruta_salida, srid_proyecto=srid, sobrescribir=True)

    rng = np.random.default_rng(semilla)

    # Ancla espacial en UTM 19S derivada dinámicamente del bbox en config/zona.yaml
    x_min, y_min = wgs84_a_utm19s(float(bbox["west"]), float(bbox["south"]))
    x_max, y_max = wgs84_a_utm19s(float(bbox["east"]), float(bbox["north"]))
    x0 = x_min + 0.15 * (x_max - x_min)
    y0 = y_min + 0.65 * (y_max - y_min)

    # Red fluvial sintética: dos cabeceras (Tipuani y Mapiri) que confluyen en Kaka -> Alto Beni
    nodos_tramos = [
        ("T-01", "Río Tipuani Alto (SIMULADO)", 2, 24.0, "T-03", [(x0, y0), (x0 + 18000, y0 - 8000)]),
        ("T-02", "Río Mapiri Medio (SIMULADO)", 2, 26.0, "T-03", [(x0 + 4000, y0 + 15000), (x0 + 18000, y0 - 8000)]),
        ("T-03", "Confluencia Guanay (SIMULADO)", 3, 22.0, "T-04", [(x0 + 18000, y0 - 8000), (x0 + 38000, y0 - 14000)]),
        ("T-04", "Río Kaka (SIMULADO)", 3, 27.0, "T-05", [(x0 + 38000, y0 - 14000), (x0 + 63000, y0 - 22000)]),
        ("T-05", "Alto Beni Entrada (SIMULADO)", 4, 25.0, None, [(x0 + 63000, y0 - 22000), (x0 + 86000, y0 - 30000)]),
    ]

    conn = sqlite3.connect(str(ruta))
    try:
        cur = conn.cursor()

        cur.execute(
            "INSERT OR REPLACE INTO schema_metadata (clave, valor) VALUES ('contiene_datos_simulados', 'true')"
        )

        # 1. Tramos de río
        tramos_geom = {}
        for tid, nombre, orden, long_km, abajo_id, coords in nodos_tramos:
            linea = LineString(coords)
            tramos_geom[tid] = linea
            cur.execute(
                """
                INSERT INTO tramos_rio
                (tramo_id, geom, nombre_rio, orden_strahler, longitud_km, tramo_aguas_abajo_id,
                 semaforo_no_depredador, semaforo_depredador, evidencia_semaforo, sintetico)
                VALUES (?, ?, ?, ?, ?, ?, 'gris', 'gris', 'sin_dato', 1)
                """,
                (tid, encode_gpkg_geom(linea, srid), nombre, orden, long_km, abajo_id),
            )

        # 2. Puntos receptores (comunidades y puntos de pesca)
        receptores = [
            ("REC-01", "Comunidad Simulada A", "comunidad", "T-01", 650, 18.0, 0.10, 0.65),
            ("REC-02", "Punto Pesca Simulado B", "punto_pesca", "T-03", 1400, 24.0, 0.35, 0.50),
            ("REC-03", "Comunidad Simulada C", "comunidad", "T-04", 2200, 26.0, 0.65, 0.55),
            ("REC-04", "Comunidad Simulada D", "comunidad", "T-05", 3100, 22.0, 0.80, 0.70),
        ]
        for rid, nombre, tipo, tid, pob, cons, agua_q, frac in receptores:
            pt = tramos_geom[tid].interpolate(frac, normalized=True)
            cur.execute(
                """
                INSERT INTO puntos_receptores
                (receptor_id, geom, nombre, tipo, tramo_id, poblacion, consumo_kg_anio, agua_quieta, sintetico)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (rid, encode_gpkg_geom(pt, srid), nombre, tipo, tid, pob, cons, agua_q),
            )

        # 3. Derechos mineros simulados (cuadrículas)
        cuadriculas = []
        for idx, tid in enumerate(["T-01", "T-02", "T-03"], start=1):
            centro = tramos_geom[tid].interpolate(0.35, normalized=True)
            poly = Polygon(
                [
                    (centro.x - 1500, centro.y - 1500),
                    (centro.x + 1500, centro.y - 1500),
                    (centro.x + 1500, centro.y + 1500),
                    (centro.x - 1500, centro.y + 1500),
                ]
            )
            cuadriculas.append(poly)
            cur.execute(
                """
                INSERT INTO derechos_mineros (derecho_id, geom, codigo_ajam, tipo_derecho, estado, fuente, sintetico)
                VALUES (?, ?, ?, 'ATE_SIMULADO', 'vigente_simulado', 'SIMULADO', 1)
                """,
                (f"DER-{idx:02d}", encode_gpkg_geom(poly, srid), f"AJAM-SIM-{idx:03d}"),
            )

        # 4. Colas candidatas simuladas
        espec_colas = [
            ("COLA-01", "T-01", 0.25, 45.0, "cola_aluvial", 18500.0, 2.8, 0.90),
            ("COLA-02", "T-01", 0.50, 120.0, "cola_aluvial", 11200.0, 2.1, 0.85),
            ("COLA-03", "T-02", 0.30, 35.0, "cola_aluvial", 24000.0, 3.2, 0.93),
            ("COLA-04", "T-02", 0.70, 210.0, "desmonte", 15000.0, 4.0, 0.78),
            ("COLA-05", "T-03", 0.20, 60.0, "cola_aluvial", 14200.0, 2.4, 0.88),
            ("COLA-06", "T-03", 0.80, 160.0, "aguas_acidas", 6800.0, 1.2, 0.74),
            ("COLA-07", "T-04", 0.25, 50.0, "cola_aluvial", 21000.0, 2.6, 0.91),
            ("COLA-08", "T-04", 0.65, 290.0, "desmonte", 9500.0, 3.0, 0.69),
            ("COLA-09", "T-05", 0.30, 85.0, "cola_aluvial", 12500.0, 2.0, 0.82),
            ("COLA-10", "T-05", 0.60, 140.0, "cola_aluvial", 8400.0, 1.8, 0.76),
        ]
        colas_centros = {}
        for idx, (cid, tid, frac, dist_ladera, tipo, area, alt, prob) in enumerate(espec_colas):
            base_pt = tramos_geom[tid].interpolate(frac, normalized=True)
            offset_y = dist_ladera if idx % 2 == 0 else -dist_ladera
            cx, cy = base_pt.x, base_pt.y + offset_y
            lado = math.sqrt(area) / 2.0
            poly = Polygon(
                [(cx - lado, cy - lado), (cx + lado, cy - lado), (cx + lado, cy + lado), (cx - lado, cy + lado)]
            )
            en_cuad = 1 if any(poly.intersects(c) for c in cuadriculas) else 0
            pendiente = float(np.round(rng.uniform(3.0, 14.0), 2))
            hand = float(np.round(rng.uniform(1.0, 8.0), 2))
            colas_centros[cid] = (Point(cx, cy), tipo)
            cur.execute(
                """
                INSERT INTO colas_candidatas
                (cola_id, geom, tipo_pasivo, area_m2, altura_m, pendiente_media_deg, hand_m,
                 f_erosion, en_cuadricula_minera, prob_deteccion, evidencia, sintetico)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'estimado', 1)
                """,
                (cid, encode_gpkg_geom(poly, srid), tipo, area, alt, pendiente, hand, 1.0, en_cuad, prob),
            )

        # 5. Fichas de campo simuladas (algunas con licencia ambiental)
        fichas_spec = [
            ("FICHA-01", "COLA-01", "si", 1, 1),
            ("FICHA-02", "COLA-03", "si", 1, 0),
            ("FICHA-03", "COLA-05", "no_sabe", 0, 0),
            ("FICHA-04", "COLA-07", "si", 1, 1),
            ("FICHA-05", "COLA-04", "no", 0, 0),
            ("FICHA-06", "COLA-09", "no_sabe", 1, 0),
        ]
        for fid, cid, indicios, interes, licencia in fichas_spec:
            pt, tipo = colas_centros[cid]
            cur.execute(
                """
                INSERT INTO fichas_campo
                (ficha_id, cola_id, geom, existe, tipo_pasivo, rango_area, rango_altura,
                 agua_presente, indicios_hg_declarativo, viviendas_cultivos_cercanos,
                 foto_ruta, qr_codigo, id_muestra, interes_reprocesar, licencia_ambiental,
                 consentimiento, responsable_privado, minutos_llenado, fecha_registro, sintetico)
                VALUES (?, ?, ?, 1, ?, '1-3_ha', '2-4_m', 1, ?, 1, 'simulado/foto.jpg', ?, ?, ?, ?, 1,
                        'SIMULADO_PRIVADO', 5.8, '2026-11-25', 1)
                """,
                (fid, cid, encode_gpkg_geom(pt, srid), tipo, indicios, f"QR-{fid}", f"M-{fid}", interes, licencia),
            )

        # 6. Muestras simuladas de peces_hg (deja T-01 y T-05 sin datos para probar estado 'gris')
        peces_spec = [
            ("PEZ-01", "T-02", "Sábalo (simulado)", "no_depredador", 0.18),
            ("PEZ-02", "T-02", "Bagre (simulado)", "depredador", 0.42),
            ("PEZ-03", "T-03", "Sábalo (simulado)", "no_depredador", 0.34),
            ("PEZ-04", "T-03", "Surubí (simulado)", "depredador", 0.88),
            ("PEZ-05", "T-03", "Sábalo (simulado)", "no_depredador", 0.41),
            ("PEZ-06", "T-04", "Sábalo (simulado)", "no_depredador", 0.62),
            ("PEZ-07", "T-04", "Dorado (simulado)", "depredador", 1.24),
            ("PEZ-08", "T-04", "Pacú (simulado)", "no_depredador", 0.48),
        ]
        for mid, tid, esp, gremio, hg in peces_spec:
            cur.execute(
                """
                INSERT INTO peces_hg
                (muestra_id, tramo_id, especie, gremio_trofico, hg_mg_kg_ph, cita,
                 metodo_analitico, limite_deteccion, calidad, fecha_muestreo, sintetico)
                VALUES (?, ?, ?, ?, ?, 'DATO SIMULADO PARA DEMOSTRACION',
                        'CV-AAS (simulado)', 0.02, 'simulado', '2026-10-15', 1)
                """,
                (mid, tid, esp, gremio, hg),
            )

        conn.commit()
    finally:
        conn.close()

    return ruta
