"""Módulo M2: Integración y validación de fichas de campo offline (QGIS / QField)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any


CAMPOS_FORMULARIO_QFIELD = [
    ("existe", "booleano", "Confirmación visual de existencia del pasivo"),
    ("tipo_pasivo", "lista", "cola_aluvial | desmonte | aguas_acidas"),
    ("rango_area", "lista", "<0.5_ha | 0.5-1_ha | 1-3_ha | >3_ha"),
    ("rango_altura", "lista", "<1_m | 1-2_m | 2-4_m | >4_m"),
    ("agua_presente", "booleano", "Presencia de agua estancada o escorrentía"),
    ("indicios_hg_declarativo", "lista", "si | no | no_sabe (solo declarativo, no acusatorio)"),
    ("viviendas_cultivos_cercanos", "booleano", "Presencia de viviendas o cultivos a <200 m"),
    ("foto_ruta", "foto", "Fotografía geolocalizada (capa restringida)"),
    ("qr_codigo", "texto", "Código QR de trazabilidad de bolsa/sitio"),
    ("id_muestra", "texto", "Identificador de muestra (si aplica, sin manipular Hg)"),
    ("interes_reprocesar", "booleano", "Interés voluntario en reprocesamiento limpio"),
    ("licencia_ambiental", "booleano", "Cuenta con licencia ambiental registrada"),
    ("consentimiento", "booleano", "Consentimiento informado de registro"),
    ("responsable_privado", "texto_opcional", "Opcional; nunca se publica en capa web"),
]


def ingestar_fichas_qfield(
    gpkg_destino: Path | str,
    gpkg_qfield: Path | str,
) -> dict[str, Any]:
    """Importa fichas verificadas desde un GeoPackage QField al GeoPackage principal.

    Marca los registros reales con `sintetico = 0` y actualiza `evidencia = 'medido'`
    en las colas verificadas que existen.
    """
    conn_qf = sqlite3.connect(str(gpkg_qfield))
    conn_dst = sqlite3.connect(str(gpkg_destino))
    try:
        fichas = conn_qf.execute(
            """
            SELECT ficha_id, cola_id, geom, existe, tipo_pasivo, rango_area, rango_altura,
                   agua_presente, indicios_hg_declarativo, viviendas_cultivos_cercanos,
                   foto_ruta, qr_codigo, id_muestra, interes_reprocesar, licencia_ambiental,
                   consentimiento, responsable_privado, minutos_llenado, fecha_registro
            FROM fichas_campo
            """
        ).fetchall()

        insertadas = 0
        for row in fichas:
            conn_dst.execute(
                """
                INSERT OR REPLACE INTO fichas_campo
                (ficha_id, cola_id, geom, existe, tipo_pasivo, rango_area, rango_altura,
                 agua_presente, indicios_hg_declarativo, viviendas_cultivos_cercanos,
                 foto_ruta, qr_codigo, id_muestra, interes_reprocesar, licencia_ambiental,
                 consentimiento, responsable_privado, minutos_llenado, fecha_registro, sintetico)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                row,
            )
            cola_id = row[1]
            existe = int(row[3])
            tipo_pasivo = row[4]
            if existe == 1:
                conn_dst.execute(
                    """
                    UPDATE colas_candidatas
                    SET tipo_pasivo = ?, evidencia = 'medido', sintetico = 0
                    WHERE cola_id = ?
                    """,
                    (tipo_pasivo, cola_id),
                )
            insertadas += 1

        conn_dst.commit()
    finally:
        conn_qf.close()
        conn_dst.close()

    return {"fichas_ingresadas": insertadas, "marcadas_como_reales": True}
