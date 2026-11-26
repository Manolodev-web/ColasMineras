"""Módulo M1: Detección satelital Sentinel-2 L2A (STAC), índices, Random Forest y bloques espaciales."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import GroupKFold

from algatech.config import cargar_configuracion


@dataclass(frozen=True)
class ResultadoValidacionM1:
    """Métricas reales de validación espacial por bloques (sin mezcla aleatoria)."""

    precision: float
    exhaustividad: float
    n_bloques: int
    n_muestras_reales: int


def calcular_indices_espectrales(
    b02: np.ndarray,
    b03: np.ndarray,
    b04: np.ndarray,
    b08: np.ndarray,
    b11: np.ndarray,
    ndvi_2019: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Calcula NDVI, MNDWI, BSI (suelo desnudo) y cambio temporal dNDVI."""
    eps = 1e-6
    b02_f = b02.astype(float)
    b03_f = b03.astype(float)
    b04_f = b04.astype(float)
    b08_f = b08.astype(float)
    b11_f = b11.astype(float)

    ndvi = (b08_f - b04_f) / (b08_f + b04_f + eps)
    mndwi = (b03_f - b11_f) / (b03_f + b11_f + eps)
    bsi = ((b11_f + b04_f) - (b08_f + b02_f)) / ((b11_f + b04_f) + (b08_f + b02_f) + eps)

    if ndvi_2019 is not None:
        dndvi = ndvi - ndvi_2019.astype(float)
    else:
        dndvi = np.zeros_like(ndvi, dtype=float)

    return {
        "ndvi": ndvi,
        "mndwi": mndwi,
        "bsi": bsi,
        "dndvi": dndvi,
    }


def asignar_bloques_espaciales(
    coords_xy: np.ndarray,
    n_bloques: int = 5,
) -> np.ndarray:
    """Asigna bloques espaciales contiguos (grilla) para evitar fuga espacial en CV."""
    if len(coords_xy) < n_bloques:
        raise ValueError("Se requieren al menos tantas muestras como bloques espaciales.")
    x = coords_xy[:, 0]
    y = coords_xy[:, 1]
    nx = max(1, int(np.ceil(np.sqrt(n_bloques))))
    ny = max(1, int(np.ceil(n_bloques / nx)))

    qx = np.floor((x - x.min()) / (max(1e-6, x.max() - x.min()) + 1e-9) * nx).astype(int)
    qy = np.floor((y - y.min()) / (max(1e-6, y.max() - y.min()) + 1e-9) * ny).astype(int)
    qx = np.clip(qx, 0, nx - 1)
    qy = np.clip(qy, 0, ny - 1)
    bloques = qy * nx + qx
    return bloques


def entrenar_y_validar_rf_espacial(
    X: np.ndarray,
    y: np.ndarray,
    coords_xy: np.ndarray,
    config_dir: Path | str | None = None,
    semilla: int = 42,
) -> tuple[RandomForestClassifier, ResultadoValidacionM1]:
    """Entrena Random Forest y valida con GroupKFold por bloques espaciales."""
    cfg = cargar_configuracion(config_dir)
    n_bloques_cfg = int(cfg.parametros["deteccion"]["n_bloques_espaciales"])

    grupos = asignar_bloques_espaciales(coords_xy, n_bloques=n_bloques_cfg)
    n_grupos_unicos = len(np.unique(grupos))
    n_splits = min(n_bloques_cfg, n_grupos_unicos)
    if n_splits < 2:
        raise ValueError("Se requieren al menos 2 bloques espaciales distintos con etiquetas.")

    gkf = GroupKFold(n_splits=n_splits)
    y_pred_oof = np.zeros_like(y)

    for train_idx, val_idx in gkf.split(X, y, groups=grupos):
        clf_cv = RandomForestClassifier(
            n_estimators=150,
            random_state=semilla,
            class_weight="balanced",
            n_jobs=1,
        )
        clf_cv.fit(X[train_idx], y[train_idx])
        y_pred_oof[val_idx] = clf_cv.predict(X[val_idx])

    prec = float(precision_score(y, y_pred_oof, zero_division=0))
    rec = float(recall_score(y, y_pred_oof, zero_division=0))

    modelo_final = RandomForestClassifier(
        n_estimators=200,
        random_state=semilla,
        class_weight="balanced",
        n_jobs=1,
    )
    modelo_final.fit(X, y)

    return modelo_final, ResultadoValidacionM1(
        precision=prec,
        exhaustividad=rec,
        n_bloques=n_splits,
        n_muestras_reales=int(len(y)),
    )


def agrupar_en_objetos_candidatos(
    mascara_prob: np.ndarray,
    pendiente_deg: np.ndarray,
    tamano_pixel_m: float = 10.0,
    umbral_prob: float = 0.60,
    config_dir: Path | str | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Agrupa píxeles candidatos en objetos aplicando reglas de área mínima y pendiente."""
    cfg = cargar_configuracion(config_dir)
    area_min = float(cfg.parametros["deteccion"]["area_min_m2"])
    pend_max = float(cfg.parametros["deteccion"]["pendiente_max_grados"])

    mascara_bin = (mascara_prob >= umbral_prob) & (pendiente_deg <= pend_max)
    etiquetas, n_obj = ndimage.label(mascara_bin)

    area_pixel = tamano_pixel_m * tamano_pixel_m
    objetos = []
    etiquetas_filtradas = np.zeros_like(etiquetas)
    nuevo_id = 0

    for obj_id in range(1, n_obj + 1):
        mask_i = etiquetas == obj_id
        area_m2 = float(mask_i.sum()) * area_pixel
        if area_m2 < area_min:
            continue
        nuevo_id += 1
        etiquetas_filtradas[mask_i] = nuevo_id
        objetos.append(
            {
                "objeto_id": nuevo_id,
                "area_m2": area_m2,
                "pendiente_media_deg": float(pendiente_deg[mask_i].mean()),
                "prob_media": float(mascara_prob[mask_i].mean()),
            }
        )

    return etiquetas_filtradas, objetos


def buscar_escenas_stac_sentinel2(config_dir: Path | str | None = None) -> dict[str, Any]:
    """Consulta escenas Sentinel-2 L2A vía STAC (Planetary Computer) según `config/zona.yaml`."""
    try:
        import pystac_client  # type: ignore
        import planetary_computer  # type: ignore
    except ImportError:
        return {
            "disponible": False,
            "motivo": "Faltan paquetes opcionales `pystac-client` y `planetary-computer`.",
            "alternativa": "Instalar con `pip install pystac-client planetary-computer rasterio` o descargar compuesto L2A desde Copernicus Data Space.",
        }

    cfg = cargar_configuracion(config_dir)
    bbox = cfg.zona["bbox_wgs84"]
    fechas = cfg.zona["fechas"]["temporada_seca_actual"]
    nub_max = cfg.zona["satelite"]["nubosidad_max_pct"]

    catalogo = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    busqueda = catalogo.search(
        collections=[cfg.zona["satelite"]["coleccion_stac"]],
        bbox=[bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
        datetime=f"{fechas['inicio']}/{fechas['fin']}",
        query={"eo:cloud_cover": {"lt": nub_max}},
    )
    items = list(busqueda.items())
    return {
        "disponible": True,
        "n_escenas": len(items),
        "ids": [it.id for it in items[:10]],
    }
