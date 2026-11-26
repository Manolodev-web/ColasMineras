"""Módulo M3: Hidrología fluvial, pegado a red de ríos y distancias aguas abajo L_ij."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3

import networkx as nx
from shapely.geometry import LineString, Point

from algatech.schema import decode_gpkg_geom


@dataclass(frozen=True)
class ProyeccionTramo:
    """Resultado de pegar una geometría (cola o receptor) a la red de tramos."""

    entidad_id: str
    tramo_id: str
    d_ladera_m: float
    fraccion_en_tramo: float  # 0.0 = inicio aguas arriba del tramo, 1.0 = fin aguas abajo


def construir_grafo_hidrologico(ruta_gpkg: Path | str) -> tuple[nx.DiGraph, dict[str, dict]]:
    """Construye un grafo dirigido de tramos de río (aguas arriba -> aguas abajo).

    Cada nodo en el grafo es un `tramo_id`. Si `tramo_A` drena hacia `tramo_B`,
    existe una arista dirigida `tramo_A -> tramo_B` con peso igual a `longitud_km`
    del tramo origen.
    """
    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        rows = conn.execute(
            """
            SELECT tramo_id, geom, nombre_rio, orden_strahler, longitud_km, tramo_aguas_abajo_id
            FROM tramos_rio
            """
        ).fetchall()
    finally:
        conn.close()

    grafo = nx.DiGraph()
    tramos_info: dict[str, dict] = {}

    for tramo_id, geom_blob, nombre, orden, long_km, abajo_id in rows:
        geom = decode_gpkg_geom(geom_blob)
        if not isinstance(geom, LineString):
            raise TypeError(f"El tramo {tramo_id} no es una LineString válida.")
        tramos_info[tramo_id] = {
            "tramo_id": tramo_id,
            "geom": geom,
            "nombre_rio": nombre,
            "orden_strahler": orden,
            "longitud_km": float(long_km),
            "tramo_aguas_abajo_id": abajo_id,
        }
        grafo.add_node(tramo_id, longitud_km=float(long_km), nombre_rio=nombre)

    for tramo_id, info in tramos_info.items():
        abajo = info["tramo_aguas_abajo_id"]
        if abajo is not None:
            if abajo not in tramos_info:
                raise ValueError(f"El tramo '{tramo_id}' apunta a '{abajo}', que no existe en tramos_rio.")
            grafo.add_edge(tramo_id, abajo, weight=info["longitud_km"])

    if not nx.is_directed_acyclic_graph(grafo):
        raise ValueError("La red de tramos contiene ciclos; debe ser un grafo acíclico dirigido.")

    return grafo, tramos_info


def pegar_punto_a_red(
    entidad_id: str,
    punto: Point,
    tramos_info: dict[str, dict],
) -> ProyeccionTramo:
    """Encuentra el tramo más cercano al punto y calcula d_ladera (m) y fracción."""
    mejor_tramo = None
    mejor_dist = math.inf
    mejor_frac = 0.0

    for tramo_id, info in tramos_info.items():
        linea: LineString = info["geom"]
        dist = punto.distance(linea)
        if dist < mejor_dist:
            mejor_dist = dist
            mejor_tramo = tramo_id
            mejor_frac = linea.project(punto, normalized=True)

    if mejor_tramo is None:
        raise ValueError("No hay tramos en tramos_rio para pegar entidades.")

    return ProyeccionTramo(
        entidad_id=entidad_id,
        tramo_id=mejor_tramo,
        d_ladera_m=float(mejor_dist),
        fraccion_en_tramo=float(mejor_frac),
    )


def distancia_aguas_abajo_km(
    grafo: nx.DiGraph,
    tramos_info: dict[str, dict],
    origen: ProyeccionTramo,
    destino: ProyeccionTramo,
) -> float:
    """Calcula la distancia L_ij (km) siguiendo el flujo desde origen hacia destino.

    Devuelve `math.inf` si el destino no está aguas abajo del origen.
    """
    if origen.tramo_id == destino.tramo_id:
        if destino.fraccion_en_tramo < origen.fraccion_en_tramo:
            return math.inf
        long_tramo = tramos_info[origen.tramo_id]["longitud_km"]
        return (destino.fraccion_en_tramo - origen.fraccion_en_tramo) * long_tramo

    try:
        camino = nx.shortest_path(grafo, source=origen.tramo_id, target=destino.tramo_id, weight="weight")
    except nx.NetworkXNoPath:
        return math.inf

    # Tramo de origen: desde la fracción de la cola hasta el final del tramo
    long_origen = tramos_info[origen.tramo_id]["longitud_km"]
    dist_km = (1.0 - origen.fraccion_en_tramo) * long_origen

    # Tramos intermedios completos
    for tramo_intermedio in camino[1:-1]:
        dist_km += tramos_info[tramo_intermedio]["longitud_km"]

    # Tramo de destino: desde inicio del tramo hasta la fracción del receptor
    long_destino = tramos_info[destino.tramo_id]["longitud_km"]
    dist_km += destino.fraccion_en_tramo * long_destino

    return float(dist_km)


def ejecutar_hidrologia(ruta_gpkg: Path | str) -> dict[str, object]:
    """Ejecuta el análisis de red hidrológica sobre un GeoPackage y retorna resumen y proyecciones."""
    grafo, tramos_info = construir_grafo_hidrologico(ruta_gpkg)

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        colas_rows = conn.execute("SELECT cola_id, geom FROM colas_candidatas").fetchall()
        rec_rows = conn.execute("SELECT receptor_id, geom, tramo_id FROM puntos_receptores").fetchall()
    finally:
        conn.close()

    proy_colas: dict[str, ProyeccionTramo] = {}
    for cola_id, geom_blob in colas_rows:
        geom = decode_gpkg_geom(geom_blob)
        centroide = geom.centroid
        proy_colas[cola_id] = pegar_punto_a_red(cola_id, centroide, tramos_info)

    proy_receptores: dict[str, ProyeccionTramo] = {}
    for rec_id, geom_blob, _tramo_id in rec_rows:
        pt = decode_gpkg_geom(geom_blob)
        proy_receptores[rec_id] = pegar_punto_a_red(rec_id, pt, tramos_info)

    matriz_L_km: dict[tuple[str, str], float] = {}
    pares_conectados = 0
    for cid, p_cola in proy_colas.items():
        for rid, p_rec in proy_receptores.items():
            dist = distancia_aguas_abajo_km(grafo, tramos_info, p_cola, p_rec)
            matriz_L_km[(cid, rid)] = dist
            if math.isfinite(dist):
                pares_conectados += 1

    return {
        "grafo": grafo,
        "tramos_info": tramos_info,
        "proy_colas": proy_colas,
        "proy_receptores": proy_receptores,
        "matriz_L_km": matriz_L_km,
        "pares_conectados": pares_conectados,
    }
