# Contrato de datos GeoPackage (`algatech.gpkg`) — Versión `1.0.0`

El almacenamiento oficial del sistema es un archivo **GeoPackage (SQLite espacial OGC)** en CRS proyectado `EPSG:32719` (WGS 84 / UTM zona 19S), compatible con QGIS, QField y Python sin necesidad de servidores.

## Reglas transversales

1. **Bandera `sintetico`:** todas las tablas operativas incluyen la columna entera `sintetico` (`1` = dato simulado de demostración, `0` = dato real). Ninguna métrica de validación debe incluir filas con `sintetico = 1`.
2. **Nivel de evidencia:** todo resultado modelado declara `evidencia` en `{'medido', 'estimado', 'sin_dato'}`.
3. **Separación de capas (diseño no punitivo):**
   - **Capa restringida (local):** archivo GeoPackage completo con `fichas_campo` (incluyendo `responsable_privado`, `consentimiento`, `foto_ruta`) y coordenadas finas.
   - **Capa pública (web):** exporta únicamente agregados por tramo, ranking sin datos personales y geometrías generalizadas.

## Tablas del esquema

| Capa / Tabla | Geometría | Clave primaria | Propósito |
| :--- | :--- | :--- | :--- |
| `colas_candidatas` | `POLYGON` | `cola_id` | Acumulaciones candidatas detectadas en M1 + atributos topográficos y cruce AJAM |
| `fichas_campo` | `POINT` | `ficha_id` | Verificación offline (~12 campos), licencia ambiental y responsable privado |
| `tramos_rio` | `LINESTRING` | `tramo_id` | Segmentos fluviales (20–30 km) conectados aguas abajo + semáforo de pescado |
| `puntos_receptores` | `POINT` | `receptor_id` | Comunidades y puntos de pesca (`poblacion`, `consumo_kg_anio`, `agua_quieta`) |
| `peces_hg` | Tabla | `muestra_id` | Concentraciones normalizadas a `mg/kg peso humedo` con trazabilidad analítica |
| `contribuciones` | Tabla | `contrib_id` | Contribución relativa `parte_p50`, `parte_p10`, `parte_p90` de cada cola a cada receptor |
| `ranking` | Tabla | `cola_id` | Índice `I` (p50/p10/p90), estabilidad top-k, `R_i`, ley de equilibrio y cuadrante |
| `derechos_mineros` *(opcional)* | `POLYGON` | `derecho_id` | Cuadrículas AJAM / catastro minero para cruce legal no punitivo |
| `schema_metadata` | Tabla | `clave` | Versión del contrato (`1.0.0`) y fecha de generación |
