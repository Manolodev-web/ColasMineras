.PHONY: datos deteccion hidrologia contribuciones semaforo ranking web validacion pruebas

PYTHON ?= python
PYTHONPATH_ENV = PYTHONPATH=src

GPKG ?= data/simulado/algatech_simulado.gpkg

datos:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.simulado import generar_gpkg_simulado; generar_gpkg_simulado()"

deteccion:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.deteccion import buscar_escenas_stac_sentinel2; print(buscar_escenas_stac_sentinel2())"

hidrologia:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.hidrologia import ejecutar_hidrologia; r=ejecutar_hidrologia('$(GPKG)'); print('Pares conectados:', r['pares_conectados'])"

contribuciones:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.contribuciones import ejecutar_contribuciones_monte_carlo; r=ejecutar_contribuciones_monte_carlo('$(GPKG)'); print('Prioritarias (>=80%):', r['prioritarias'])"

semaforo:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.semaforo import generar_comunicacion_comunitaria; print(generar_comunicacion_comunitaria('$(GPKG)'))"

ranking:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.ranking import calcular_ranking_y_cuadrantes; r=calcular_ranking_y_cuadrantes('$(GPKG)'); print('Muestreo:', [d['cola_id'] for d in r['donde_muestrear']])"

web:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.export_web import exportar_capa_publica_web; from algatech.fichas_pdf import generar_fichas_pdf; print(exportar_capa_publica_web('$(GPKG)')); print('PDFs:', len(generar_fichas_pdf('$(GPKG)')))"

validacion:
	$(PYTHON) -c "import sys; sys.path.insert(0, 'src'); from algatech.validacion import generar_informe_validacion; print(generar_informe_validacion('$(GPKG)'))"

pruebas:
	$(PYTHON) -m pytest -v
