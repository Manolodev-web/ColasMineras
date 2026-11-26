# Guía de Ficha de Campo Offline (QGIS / QField) — Módulo M2

- **Meta operativa:** menos de **8 minutos** por ficha.
- **Diseño no punitivo y seguro:**
  - La ficha es voluntaria (`consentimiento = true`).
  - El campo `responsable_privado` es **opcional** y pertenece exclusivamente a la capa restringida.
  - **Seguridad:** el técnico **nunca debe manipular mercurio** en campo; solo registra indicios declarativos (`si / no / no_sabe`) y toma muestras de agua/sedimento/material según protocolo seguro.

## Campos del formulario (~12 campos principales + consentimiento)

1. `existe` (Sí / No): confirmación visual del pasivo detectado por satélite.
2. `tipo_pasivo`: `cola_aluvial`, `desmonte` o `aguas_acidas`.
3. `rango_area`: `<0.5_ha`, `0.5-1_ha`, `1-3_ha`, `>3_ha`.
4. `rango_altura`: `<1_m`, `1-2_m`, `2-4_m`, `>4_m`.
5. `agua_presente` (Sí / No): presencia de agua quieta o escorrentía en contacto.
6. `indicios_hg_declarativo`: `si`, `no`, `no_sabe`.
7. `viviendas_cultivos_cercanos` (Sí / No): dentro de 200 m.
8. `foto_ruta`: fotografía geolocalizada desde QField.
9. `qr_codigo`: lectura QR del sitio o bolsa de muestra.
10. `id_muestra`: código de cadena de custodia.
11. `interes_reprocesar` (Sí / No): interés en tecnologías gravimétricas limpias.
12. `licencia_ambiental` (Sí / No): requerido para habilitar la etiqueta *Reprocesable*.
13. `consentimiento` (Sí / No) y `responsable_privado` (opcional, privado).

## Flujo de sincronización con M1

Al volver de campo, ejecutar:
```python
from algatech.qfield import ingestar_fichas_qfield
ingestar_fichas_qfield("data/processed/algatech.gpkg", "data/raw/campo_qfield.gpkg")
```
Las fichas verificadas quedan marcadas con `sintetico = 0` y regresan a M1 como etiquetas reales para reentrenar el modelo Random Forest.
