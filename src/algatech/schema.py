"""Contrato de datos GeoPackage (OGC) y versionado del esquema AlgaTech."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import struct
from typing import Iterable

from shapely import wkb
from shapely.geometry.base import BaseGeometry

from algatech import SCHEMA_VERSION


CAPAS_OBLIGATORIAS = (
    "colas_candidatas",
    "fichas_campo",
    "tramos_rio",
    "puntos_receptores",
    "peces_hg",
    "contribuciones",
    "ranking",
)

CAPAS_OPCIONALES = ("derechos_mineros",)

# Columnas restringidas que NUNCA deben exportarse a la capa pública web
COLUMNAS_RESTRINGIDAS = {
    "fichas_campo": ("responsable_privado", "consentimiento", "foto_ruta"),
}


def encode_gpkg_geom(geom: BaseGeometry | None, srid: int = 32719) -> bytes | None:
    """Codifica una geometría Shapely al formato binario estándar GeoPackage (GPB)."""
    if geom is None:
        return None
    # Header GPB: magic 'GP', version 0, flags 0x01 (little endian, sin envelope), srs_id int32
    header = struct.pack("<2sBBi", b"GP", 0, 1, srid)
    return header + wkb.dumps(geom)


def decode_gpkg_geom(blob: bytes | None) -> BaseGeometry | None:
    """Decodifica un blob GeoPackage Binary (GPB) a geometría Shapely."""
    if blob is None:
        return None
    if len(blob) < 8 or blob[:2] != b"GP":
        raise ValueError("Blob de geometría GeoPackage inválido.")
    flags = blob[3]
    envelope_indicator = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_indicator not in envelope_sizes:
        raise ValueError(f"Indicador de envelope GPB no soportado: {envelope_indicator}")
    wkb_offset = 8 + envelope_sizes[envelope_indicator]
    return wkb.loads(blob[wkb_offset:])


def _inicializar_tablas_ogc(conn: sqlite3.Connection, srid_proyecto: int) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER,
            CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );

        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name),
            CONSTRAINT fk_gc_tn FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
            CONSTRAINT fk_gc_srs FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        """
    )

    srs_rows = [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
        (
            "WGS 84 geodetic",
            4326,
            "EPSG",
            4326,
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
            "WGS 84",
        ),
        (
            f"WGS 84 / UTM zone 19S (EPSG:{srid_proyecto})",
            srid_proyecto,
            "EPSG",
            srid_proyecto,
            f'PROJCS["EPSG:{srid_proyecto}",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],UNIT["metre",1]]',
            "CRS proyectado del piloto",
        ),
    ]
    cur.executemany(
        """
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys
        (srs_name, srs_id, organization, organization_coordsys_id, definition, description)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        srs_rows,
    )


def crear_esquema_geopackage(
    ruta_gpkg: Path | str,
    srid_proyecto: int = 32719,
    sobrescribir: bool = False,
) -> Path:
    """Crea un GeoPackage vacío con todas las tablas, claves y registros OGC del contrato."""
    ruta = Path(ruta_gpkg)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if sobrescribir and ruta.exists():
        ruta.unlink()

    conn = sqlite3.connect(str(ruta))
    try:
        _inicializar_tablas_ogc(conn, srid_proyecto)
        cur = conn.cursor()

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_metadata (
                clave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS colas_candidatas (
                cola_id TEXT PRIMARY KEY,
                geom BLOB NOT NULL,
                tipo_pasivo TEXT NOT NULL,
                area_m2 REAL NOT NULL CHECK (area_m2 >= 0),
                altura_m REAL CHECK (altura_m IS NULL OR altura_m >= 0),
                pendiente_media_deg REAL,
                hand_m REAL,
                f_erosion REAL DEFAULT 1.0,
                en_cuadricula_minera INTEGER NOT NULL DEFAULT 0 CHECK (en_cuadricula_minera IN (0, 1)),
                prob_deteccion REAL CHECK (prob_deteccion IS NULL OR (prob_deteccion >= 0 AND prob_deteccion <= 1)),
                evidencia TEXT NOT NULL CHECK (evidencia IN ('medido', 'estimado', 'sin_dato')),
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS fichas_campo (
                ficha_id TEXT PRIMARY KEY,
                cola_id TEXT NOT NULL,
                geom BLOB NOT NULL,
                existe INTEGER NOT NULL CHECK (existe IN (0, 1)),
                tipo_pasivo TEXT NOT NULL,
                rango_area TEXT,
                rango_altura TEXT,
                agua_presente INTEGER NOT NULL CHECK (agua_presente IN (0, 1)),
                indicios_hg_declarativo TEXT NOT NULL CHECK (indicios_hg_declarativo IN ('si', 'no', 'no_sabe')),
                viviendas_cultivos_cercanos INTEGER NOT NULL CHECK (viviendas_cultivos_cercanos IN (0, 1)),
                foto_ruta TEXT,
                qr_codigo TEXT,
                id_muestra TEXT,
                interes_reprocesar INTEGER NOT NULL DEFAULT 0 CHECK (interes_reprocesar IN (0, 1)),
                licencia_ambiental INTEGER NOT NULL DEFAULT 0 CHECK (licencia_ambiental IN (0, 1)),
                consentimiento INTEGER NOT NULL CHECK (consentimiento IN (0, 1)),
                responsable_privado TEXT,
                minutos_llenado REAL CHECK (minutos_llenado IS NULL OR minutos_llenado >= 0),
                fecha_registro TEXT NOT NULL,
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1)),
                FOREIGN KEY (cola_id) REFERENCES colas_candidatas(cola_id)
            );

            CREATE TABLE IF NOT EXISTS tramos_rio (
                tramo_id TEXT PRIMARY KEY,
                geom BLOB NOT NULL,
                nombre_rio TEXT NOT NULL,
                orden_strahler INTEGER,
                longitud_km REAL NOT NULL CHECK (longitud_km > 0),
                tramo_aguas_abajo_id TEXT,
                semaforo_no_depredador TEXT NOT NULL DEFAULT 'gris',
                semaforo_depredador TEXT NOT NULL DEFAULT 'gris',
                evidencia_semaforo TEXT NOT NULL DEFAULT 'sin_dato' CHECK (evidencia_semaforo IN ('medido', 'estimado', 'sin_dato')),
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1))
            );

            CREATE TABLE IF NOT EXISTS puntos_receptores (
                receptor_id TEXT PRIMARY KEY,
                geom BLOB NOT NULL,
                nombre TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('comunidad', 'punto_pesca')),
                tramo_id TEXT NOT NULL,
                poblacion INTEGER NOT NULL CHECK (poblacion >= 0),
                consumo_kg_anio REAL NOT NULL CHECK (consumo_kg_anio >= 0),
                agua_quieta REAL NOT NULL DEFAULT 0.0 CHECK (agua_quieta >= 0 AND agua_quieta <= 1),
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1)),
                FOREIGN KEY (tramo_id) REFERENCES tramos_rio(tramo_id)
            );

            CREATE TABLE IF NOT EXISTS peces_hg (
                muestra_id TEXT PRIMARY KEY,
                tramo_id TEXT NOT NULL,
                especie TEXT NOT NULL,
                gremio_trofico TEXT NOT NULL CHECK (gremio_trofico IN ('no_depredador', 'depredador')),
                hg_mg_kg_ph REAL NOT NULL CHECK (hg_mg_kg_ph >= 0),
                cita TEXT NOT NULL,
                metodo_analitico TEXT NOT NULL,
                limite_deteccion REAL NOT NULL CHECK (limite_deteccion >= 0),
                calidad TEXT NOT NULL,
                fecha_muestreo TEXT NOT NULL,
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1)),
                FOREIGN KEY (tramo_id) REFERENCES tramos_rio(tramo_id)
            );

            CREATE TABLE IF NOT EXISTS contribuciones (
                contrib_id TEXT PRIMARY KEY,
                cola_id TEXT NOT NULL,
                receptor_id TEXT NOT NULL,
                distancia_rio_km REAL NOT NULL CHECK (distancia_rio_km >= 0),
                parte_p50 REAL NOT NULL CHECK (parte_p50 >= 0 AND parte_p50 <= 1),
                parte_p10 REAL NOT NULL CHECK (parte_p10 >= 0 AND parte_p10 <= 1),
                parte_p90 REAL NOT NULL CHECK (parte_p90 >= 0 AND parte_p90 <= 1),
                c_ij_p50 REAL NOT NULL CHECK (c_ij_p50 >= 0),
                evidencia TEXT NOT NULL CHECK (evidencia IN ('medido', 'estimado', 'sin_dato')),
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1)),
                FOREIGN KEY (cola_id) REFERENCES colas_candidatas(cola_id),
                FOREIGN KEY (receptor_id) REFERENCES puntos_receptores(receptor_id)
            );

            CREATE TABLE IF NOT EXISTS ranking (
                cola_id TEXT PRIMARY KEY,
                tipo_pasivo TEXT NOT NULL,
                I_p50 REAL NOT NULL CHECK (I_p50 >= 0),
                I_p10 REAL NOT NULL CHECK (I_p10 >= 0),
                I_p90 REAL NOT NULL CHECK (I_p90 >= 0),
                prob_top_k REAL NOT NULL CHECK (prob_top_k >= 0 AND prob_top_k <= 1),
                es_prioritaria INTEGER NOT NULL CHECK (es_prioritaria IN (0, 1)),
                R_i REAL NOT NULL CHECK (R_i >= 0 AND R_i <= 1),
                ley_equilibrio_g_t REAL,
                reprocesable INTEGER NOT NULL CHECK (reprocesable IN (0, 1)),
                cuadrante TEXT NOT NULL,
                prioridad_muestreo INTEGER NOT NULL CHECK (prioridad_muestreo IN (0, 1)),
                evidencia TEXT NOT NULL CHECK (evidencia IN ('medido', 'estimado', 'sin_dato')),
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1)),
                FOREIGN KEY (cola_id) REFERENCES colas_candidatas(cola_id)
            );

            CREATE TABLE IF NOT EXISTS derechos_mineros (
                derecho_id TEXT PRIMARY KEY,
                geom BLOB NOT NULL,
                codigo_ajam TEXT NOT NULL,
                tipo_derecho TEXT NOT NULL,
                estado TEXT NOT NULL,
                fuente TEXT NOT NULL,
                sintetico INTEGER NOT NULL CHECK (sintetico IN (0, 1))
            );
            """
        )

        capas_espaciales = [
            ("colas_candidatas", "POLYGON", srid_proyecto, "Colas y pasivos mineros candidatos"),
            ("fichas_campo", "POINT", srid_proyecto, "Fichas de verificación de campo offline (contiene campos restringidos)"),
            ("tramos_rio", "LINESTRING", srid_proyecto, "Tramos fluviales (20-30 km) con semáforo de consumo"),
            ("puntos_receptores", "POINT", srid_proyecto, "Comunidades y puntos de pesca receptores"),
            ("derechos_mineros", "POLYGON", srid_proyecto, "Cuadrículas de derechos mineros (AJAM / catastro)"),
        ]
        for tabla, geom_type, srs_id, desc in capas_espaciales:
            cur.execute(
                """
                INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier, description, srs_id)
                VALUES (?, 'features', ?, ?, ?)
                """,
                (tabla, tabla, desc, srs_id),
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
                VALUES (?, 'geom', ?, ?, 0, 0)
                """,
                (tabla, geom_type, srs_id),
            )

        tablas_atributos = [
            ("peces_hg", "Concentraciones de Hg en tejido de pescado normalizadas a mg/kg peso húmedo"),
            ("contribuciones", "Atribución probabilística aguas abajo (mediana y p10-p90)"),
            ("ranking", "Priorización multicriterio, ley de equilibrio y cuadrantes de acción"),
            ("schema_metadata", "Metadatos y versión del contrato de datos"),
        ]
        for tabla, desc in tablas_atributos:
            cur.execute(
                """
                INSERT OR IGNORE INTO gpkg_contents (table_name, data_type, identifier, description, srs_id)
                VALUES (?, 'attributes', ?, ?, -1)
                """,
                (tabla, tabla, desc),
            )

        ahora = datetime.now(timezone.utc).isoformat()
        cur.executemany(
            "INSERT OR REPLACE INTO schema_metadata (clave, valor) VALUES (?, ?)",
            [
                ("schema_version", SCHEMA_VERSION),
                ("created_at_utc", ahora),
                ("srid_proyecto", str(srid_proyecto)),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    return ruta


def listar_tablas_gpkg(ruta_gpkg: Path | str) -> list[str]:
    """Devuelve la lista de tablas registradas en gpkg_contents."""
    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        rows = conn.execute("SELECT table_name FROM gpkg_contents ORDER BY table_name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def verificar_columnas_obligatorias(ruta_gpkg: Path | str, tablas: Iterable[str] = CAPAS_OBLIGATORIAS) -> None:
    """Verifica que todas las capas obligatorias existan y contengan la columna `sintetico`."""
    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        existentes = set(listar_tablas_gpkg(ruta_gpkg))
        for tabla in tablas:
            if tabla not in existentes:
                raise AssertionError(f"Falta la capa obligatoria '{tabla}' en {ruta_gpkg}")
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if "sintetico" not in cols:
                raise AssertionError(f"La tabla '{tabla}' no tiene la columna obligatoria 'sintetico'")
    finally:
        conn.close()
