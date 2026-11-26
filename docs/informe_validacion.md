# Informe de Validación Científica — AlgaTech (ORO-4.2)

> **Principio de honestidad científica:** Ningún dato marcado con `sintetico=1` se utiliza en las métricas de validación. Cuando faltan datos reales, se declara explícitamente.

## 1. Detección satelital (M1 — bloques espaciales)
- **Estado:** PENDIENTE DE DATOS REALES (requiere polígonos de etiquetas en campo).

## 2. Eficiencia de ficha de campo (M2 — meta < 8 min)
- **Estado:** PENDIENTE DE DATOS REALES (0 fichas con `sintetico=0`).

## 3. Concordancia del ranking con juicio de expertos
- **Estado:** PENDIENTE DE DATOS REALES (requiere ordenamiento de expertos sobre sitios reales).

## 4. Correlación con Hg en peces (`peces_hg`, Spearman por gremio)
- **Estado:** No calculable (todas las muestras reales [n=10] pertenecen a un único tramo).

## 5. Análisis de sensibilidad Monte Carlo (500 sorteos)
- **Amplitud relativa mediana (p90 - p10) / p50:** 0.00
- **Colas con estabilidad >= 80% en top-k:** 5 de 74
