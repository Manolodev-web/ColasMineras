# AlgaTech — ORO-4.2: Colas con mercurio: encontrarlas, medirlas, priorizarlas

Sistema abierto, modular y sin servidores para detectar colas mineras candidatas, verificarlas en campo offline, modelar su contribución hidrológica aguas abajo con incertidumbre (Monte Carlo), publicar un semáforo comunitario de consumo de pescado y priorizar sitios para inspección, muestreo y eventual remediación o reprocesamiento con licencia.

> **Aviso de transparencia:** Mientras se incorporan datos reales de campo y laboratorio, el repositorio incluye un conjunto de datos **SIMULADOS** (`sintetico=true`) en `data/simulado/algatech_simulado.gpkg` únicamente para demostración y pruebas de software. No deben usarse en métricas de validación.

## Principios del diseño

1. **Índices relativos e incertidumbre explícita:** nunca se reportan masas absolutas de mercurio sin medición; los parámetros inciertos ($D$, $\lambda$) se propagan con Monte Carlo (500 sorteos, mediana y rango p10–p90).
2. **Declaración de evidencia:** todo resultado declara si es `medido`, `estimado` o `sin_dato`. Un tramo nunca aparece en rojo solo por el modelo.
3. **Diseño no punitivo:** la ficha de campo es voluntaria, el campo de responsable es opcional y privado (`capa restringida`), y nunca se publica en la web estática (`capa pública`).
4. **Software libre y costo cero:** Python + GeoPackage (SQLite espacial) + QGIS/QField + web estática (alojable gratis en GitHub Pages / Cloudflare Pages).

## Estructura del repositorio

- `config/`: parámetros editables (`zona.yaml`, `parametros.yaml`, `umbrales.yaml`, `pesos.yaml`).
- `data/`: `raw/` (entradas reales), `processed/` (salidas operativas), `simulado/` (datos sintéticos marcados).
- `src/algatech/`: código fuente modular y plugins de fuentes (`cola_aluvial`, `desmonte`, `aguas_acidas`).
- `tests/`: pruebas automáticas (`pytest`).
- `docs/`: documentación técnica y contrato de datos (`esquema_gpkg.md`).
- `web/`: visor estático público (Fase 3).

## Guía rápida para operación trimestral (técnico de gobernación)

1. Actualizar los archivos en `config/` si cambia la cuenca, los umbrales de mercurio o los pesos de priorización.
2. Colocar las nuevas capas de entrada en `data/raw/` (etiquetas verificadas, DEM, derechos mineros AJAM, tabla `peces_hg`).
3. Ejecutar los objetivos del flujo:
   ```bash
   make datos
   make hidrologia
   make contribuciones
   make semaforo
   make ranking
   make web
   make pruebas
   ```
4. Abrir `data/processed/algatech.gpkg` en QGIS (capa completa) o publicar la carpeta `web/` en GitHub Pages (capa pública).
