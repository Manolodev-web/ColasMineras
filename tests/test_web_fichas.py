"""Pruebas de Fase 3: exportación pública web (privacidad) y generación de fichas PDF."""

from __future__ import annotations

import json
from pathlib import Path

from algatech.contribuciones import ejecutar_contribuciones_monte_carlo
from algatech.export_web import exportar_capa_publica_web, utm19s_a_wgs84
from algatech.fichas_pdf import generar_fichas_pdf
from algatech.ranking import calcular_ranking_y_cuadrantes
from algatech.semaforo import calcular_semaforo_pescado
from algatech.simulado import generar_gpkg_simulado, wgs84_a_utm19s


def test_roundtrip_utm19s_wgs84():
    lon, lat = -67.85, -15.52
    e, n = wgs84_a_utm19s(lon, lat)
    lon2, lat2 = utm19s_a_wgs84(e, n)
    assert abs(lon - lon2) < 1e-4
    assert abs(lat - lat2) < 1e-4


def test_export_web_privacidad_y_pdfs(tmp_path: Path):
    ruta = tmp_path / "sim.gpkg"
    generar_gpkg_simulado(ruta_salida=ruta)
    ejecutar_contribuciones_monte_carlo(ruta)
    calcular_semaforo_pescado(ruta)
    calcular_ranking_y_cuadrantes(ruta)

    ruta_json = exportar_capa_publica_web(ruta, carpeta_web_data=tmp_path / "web_data")
    texto_json = ruta_json.read_text(encoding="utf-8")
    payload = json.loads(texto_json)

    assert payload["metadata"]["contiene_datos_simulados"] is True
    assert len(payload["colas"]["features"]) == 10
    assert len(payload["tramos"]["features"]) == 5
    assert len(payload["receptores"]["features"]) == 4

    # Verificar que jamás se filtran campos privados/restringidos
    assert "responsable_privado" not in texto_json
    assert "SIMULADO_PRIVADO" not in texto_json
    assert "consentimiento" not in texto_json

    pdfs = generar_fichas_pdf(ruta, carpeta_web_fichas=tmp_path / "fichas")
    assert len(pdfs) == 10
    for pdf in pdfs:
        assert pdf.exists()
        assert pdf.read_bytes().startswith(b"%PDF-1.4")
