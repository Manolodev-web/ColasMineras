const COLORES_SEMAFORO = {
  verde: "#16a34a",
  amarillo: "#eab308",
  rojo: "#dc2626",
  gris: "#d8b4fe", // Lila claro discontinuo para contrastar con satélite y azul de comunidades
};

const ETIQUETA_CUADRANTE = {
  remediar_y_reprocesar: "Remediar y reprocesar (con licencia)",
  remediar_con_fondos_publicos: "Remediar con fondos públicos",
  reprocesar_solo_con_licencia: "Reprocesar solo con licencia",
  vigilar: "Vigilar",
};

let datos = null;
let datosBolivia = null;
let mapa = null;
let capasBase = {};
let capaBaseActual = null;
let capaTramos = null;
let capaColas = null;
let capaReceptores = null;
let capaBolivia = null;
let vistaBoliviaActiva = false;
let colasResaltadas = new Set();
let colaSeleccionadaId = null;

function colorPorRiesgo(r) {
  if (r >= 0.75) return "#ef4444";
  if (r >= 0.50) return "#f97316";
  if (r >= 0.25) return "#eab308";
  return "#06b6d4";
}

async function iniciar() {
  const resp = await fetch("data/datos_publicos.json");
  datos = await resp.json();

  if (datos.metadata.contiene_datos_simulados) {
    document.getElementById("banner-simulado").classList.remove("oculto");
  }
  document.getElementById("subtitulo-zona").textContent =
    `${datos.metadata.zona_nombre} · Esquema v${datos.metadata.schema_version}`;
  document.getElementById("mensaje-comunitario").textContent =
    datos.metadata.mensaje_comunitario;

  document.getElementById("kpi-colas").textContent = datos.colas.features.length;
  document.getElementById("kpi-tramos").textContent = datos.tramos.features.length;
  document.getElementById("kpi-comunidades").textContent = datos.receptores.features.length;
  const pobTotal = datos.receptores.features.reduce((acc, f) => acc + (f.properties.poblacion || 0), 0);
  document.getElementById("kpi-poblacion").textContent = pobTotal.toLocaleString("es-BO");

  const pDef = datos.metadata.pesos_defecto;
  document.getElementById("w-impacto").value = Math.round(pDef.peso_impacto_I * 100);
  document.getElementById("w-poblacion").value = Math.round(pDef.peso_poblacion_aguas_abajo * 100);
  document.getElementById("w-agua").value = Math.round(pDef.peso_agua_quieta * 100);

  iniciarMapa();
  recalcularPesosYMatriz();
  renderizarPanelConsumo();
  renderizarListaMuestreo();

  if (datos.colas.features.length > 0) {
    seleccionarCola(datos.colas.features[0].properties.cola_id, false);
  }

  ["w-impacto", "w-poblacion", "w-agua"].forEach((id) => {
    document.getElementById(id).addEventListener("input", recalcularPesosYMatriz);
  });
  document.getElementById("select-gremio").addEventListener("change", () => {
    renderizarTramos();
    renderizarPanelConsumo();
  });
}

function iniciarMapa() {
  mapa = L.map("mapa", { maxZoom: 19, minZoom: 5 }).setView([-15.5, -67.7], 10);

  // maxNativeZoom evita "Map data not available" y permite 2 niveles extra de zoom suave
  capasBase = {
    satelite: L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { attribution: "Tiles &copy; Esri — World Imagery", maxNativeZoom: 17, maxZoom: 19 }
    ),
    topo: L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenTopoMap (CC-BY-SA)",
      maxNativeZoom: 16,
      maxZoom: 19,
    }),
    osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxNativeZoom: 18,
      maxZoom: 19,
    }),
  };

  capaBaseActual = capasBase.satelite.addTo(mapa);

  renderizarTramos();
  renderizarColas();
  renderizarReceptores();

  if (capaColas.getBounds().isValid()) {
    mapa.fitBounds(capaColas.getBounds().pad(0.18));
  }
}

function cambiarMapaBase(tipo) {
  if (!capasBase[tipo]) return;
  if (capaBaseActual) mapa.removeLayer(capaBaseActual);
  capaBaseActual = capasBase[tipo].addTo(mapa);
  document.querySelectorAll(".mini-btn").forEach((b) => b.classList.remove("activo"));
  const mapBtn = { satelite: "btn-base-sat", topo: "btn-base-topo", osm: "btn-base-osm" };
  document.getElementById(mapBtn[tipo]).classList.add("activo");
}

function renderizarTramos() {
  if (capaTramos) mapa.removeLayer(capaTramos);
  const gremio = document.getElementById("select-gremio").value;
  const campo = gremio === "depredador" ? "semaforo_depredador" : "semaforo_no_depredador";

  capaTramos = L.geoJSON(datos.tramos, {
    style: (feat) => {
      const estado = feat.properties[campo];
      const sinDato = estado === "gris";
      return {
        color: COLORES_SEMAFORO[estado] || "#d8b4fe",
        weight: sinDato ? 3 : 6,
        opacity: sinDato ? 0.85 : 0.95,
        dashArray: sinDato ? "6 5" : null,
      };
    },
    onEachFeature: (feat, layer) => {
      const p = feat.properties;
      layer.bindPopup(
        `<strong>${p.nombre_rio}</strong><br/>` +
        `Longitud: ${p.longitud_km} km<br/>` +
        `Semáforo (${gremio}): <b>${p[campo] === "gris" ? "SIN DATO (Prioridad muestreo)" : p[campo].toUpperCase()}</b><br/>` +
        `Evidencia: ${p.evidencia_semaforo}`
      );
    },
  }).addTo(mapa);
}

function renderizarColas() {
  if (capaColas) mapa.removeLayer(capaColas);
  capaColas = L.geoJSON(datos.colas, {
    style: (feat) => {
      const p = feat.properties;
      const cid = p.cola_id;
      const r = p.R_i_actual !== undefined ? p.R_i_actual : p.R_i;
      const esResaltada = colasResaltadas.has(cid);
      const esSel = colaSeleccionadaId === cid;
      const fill = colorPorRiesgo(r);
      return {
        color: esSel ? "#ffffff" : esResaltada ? "#38bdf8" : "#1e293b",
        weight: esSel ? 4 : esResaltada ? 3.5 : 1.5,
        fillColor: fill,
        fillOpacity: esSel || esResaltada ? 0.9 : 0.72,
      };
    },
    onEachFeature: (feat, layer) => {
      const p = feat.properties;
      const r = p.R_i_actual !== undefined ? p.R_i_actual : p.R_i;
      layer.on("click", () => seleccionarCola(p.cola_id, false));
      layer.bindTooltip(`${p.cola_id} · R=${r.toFixed(2)} · ${p.fuente_poligono}`);
    },
  }).addTo(mapa);
}

function renderizarReceptores() {
  if (capaReceptores) mapa.removeLayer(capaReceptores);
  capaReceptores = L.geoJSON(datos.receptores, {
    pointToLayer: (feat, latlng) => {
      const tienePob = (feat.properties.poblacion || 0) > 0;
      return L.circleMarker(latlng, {
        radius: tienePob ? 8 : 5,
        color: "#ffffff",
        weight: 1.5,
        fillColor: tienePob ? "#2563eb" : "#60a5fa",
        fillOpacity: 0.92,
      });
    },
    onEachFeature: (feat, layer) => {
      layer.on("click", () => seleccionarComunidad(feat.properties));
      const pobTxt = feat.properties.poblacion > 0 ? ` (${feat.properties.poblacion.toLocaleString("es-BO")} hab.)` : "";
      layer.bindTooltip(`${feat.properties.nombre}${pobTxt}`);
    },
  }).addTo(mapa);
}

function activarTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("activo", b.dataset.tab === tabId));
  document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("activo", p.id === tabId));
}

function volarATop1() {
  const ordenadas = [...datos.colas.features].sort(
    (a, b) => (b.properties.R_i_actual ?? b.properties.R_i) - (a.properties.R_i_actual ?? a.properties.R_i)
  );
  if (ordenadas.length > 0) {
    activarTab("tab-sitio");
    seleccionarCola(ordenadas[0].properties.cola_id, true);
  }
}

function resaltarCampanaMuestreo() {
  activarTab("tab-campana");
  const ids = datos.colas.features.filter((f) => f.properties.prioridad_muestreo).map((f) => f.properties.cola_id);
  colasResaltadas = new Set(ids);
  renderizarColas();
  if (capaColas.getBounds().isValid()) {
    mapa.fitBounds(capaColas.getBounds().pad(0.15));
  }
}

function volarAComunidad(nombreBuscado) {
  const feat = datos.receptores.features.find(
    (f) => f.properties.nombre.toLowerCase().includes(nombreBuscado.toLowerCase())
  );
  if (!feat) return;
  activarTab("tab-sitio");
  const [lon, lat] = feat.geometry.coordinates;
  mapa.flyTo([lat, lon], 13, { duration: 0.9 });
  seleccionarComunidad(feat.properties);
}

function verCasoPecesBeni() {
  activarTab("tab-consumo");
  const tramoRurre = datos.tramos.features.find((f) => f.properties.tramo_id === "TRAMO-BENI-RURRE");
  if (tramoRurre) {
    const [lon, lat] = tramoRurre.geometry.coordinates[0];
    mapa.flyTo([lat, lon], 12, { duration: 0.9 });
  }
}

async function alternarVistaBolivia() {
  const btn = document.getElementById("btn-bolivia");
  const badge = document.getElementById("mapa-estado-badge");

  if (vistaBoliviaActiva) {
    if (capaBolivia) mapa.removeLayer(capaBolivia);
    vistaBoliviaActiva = false;
    btn.textContent = "🇧🇴 Vista Nacional Bolivia";
    badge.textContent = "🛰️ Vista Satelital Real (Esri · Zoom 19x)";
    if (capaColas.getBounds().isValid()) mapa.fitBounds(capaColas.getBounds().pad(0.18));
    return;
  }

  if (!datosBolivia) {
    try {
      const resp = await fetch("data/bolivia_mineria_resumen.json");
      datosBolivia = await resp.json();
    } catch {
      alert("Capa nacional no disponible.");
      return;
    }
  }

  const markers = datosBolivia.puntos.map((pt) =>
    L.circleMarker([pt.lat, pt.lon], {
      radius: Math.min(10, Math.max(3.5, Math.sqrt(pt.area_km2) * 3)),
      color: "#facc15",
      weight: 1,
      fillColor: "#ef4444",
      fillOpacity: 0.72,
    }).bindTooltip(`Sitio Bolivia ${pt.id} (${pt.area_km2} km²)`)
  );
  capaBolivia = L.layerGroup(markers).addTo(mapa);
  mapa.flyTo([-16.5, -64.8], 6, { duration: 0.9 });
  vistaBoliviaActiva = true;
  btn.textContent = "🔙 Volver a Piloto La Paz";
  badge.textContent = `🇧🇴 Vista Nacional: ${datosBolivia.total} polígonos mineros (GMP v2)`;
}

function seleccionarComunidad(p) {
  colasResaltadas = new Set((p.top_3_colas || []).map((c) => c.cola_id));
  renderizarColas();

  let html = `<strong>${p.nombre}</strong> <span class="badge badge-info">${p.tramo_id}</span><br/>`;
  html += `<small>Población Censo 2024: <b>${p.poblacion > 0 ? p.poblacion.toLocaleString("es-BO") : "Sin dato INE"}</b></small>`;
  if (!p.top_3_colas || p.top_3_colas.length === 0) {
    html += `<p class="ayuda" style="margin-top:6px;">Sin colas conectadas aguas arriba en la red actual.</p>`;
  } else {
    html += `<ol style="padding-left:18px;margin:6px 0;font-size:0.8rem;">`;
    p.top_3_colas.forEach((c) => {
      html += `<li><a href="#" onclick="seleccionarCola('${c.cola_id}', true);return false;"><b>${c.cola_id}</b></a>: `;
      html += `<b>${(c.parte_p50 * 100).toFixed(1)}%</b> `;
      html += `<small>(p10–p90: ${(c.parte_p10 * 100).toFixed(1)}–${(c.parte_p90 * 100).toFixed(1)}%, ${c.distancia_rio_km} km)</small></li>`;
    });
    html += `</ol>`;
  }
  document.getElementById("detalle-comunidad").innerHTML = html;
}

function seleccionarCola(colaId, hacerZoom = false) {
  colaSeleccionadaId = colaId;
  const feat = datos.colas.features.find((f) => f.properties.cola_id === colaId);
  if (!feat) return;
  const p = feat.properties;
  renderizarColas();

  if (hacerZoom && p.centroide_wgs84) {
    mapa.flyTo(p.centroide_wgs84, 16, { duration: 0.9 });
  }

  const rVal = p.R_i_actual !== undefined ? p.R_i_actual : p.R_i;
  const cuad = p.cuadrante_actual || p.cuadrante;
  const ley = p.ley_equilibrio_g_t !== null ? `${p.ley_equilibrio_g_t.toFixed(3)} g Au/t` : "N/D";
  const areaHa = (p.area_m2 / 10000).toFixed(2);

  document.getElementById("detalle-cola").innerHTML = `
    <div><strong>${p.cola_id}</strong> <span class="badge badge-info">${p.fuente_poligono}</span></div>
    <div class="kv-grid">
      <div><b>Área:</b> ${areaHa} ha</div>
      <div><b>Riesgo R<sub>i</sub>:</b> ${rVal.toFixed(3)}</div>
      <div><b>Índice I (p50):</b> ${p.I_p50}</div>
      <div><b>Rango p10–p90:</b> [${p.I_p10}, ${p.I_p90}]</div>
      <div><b>Estabilidad top-k:</b> ${(p.prob_top_k * 100).toFixed(1)}%</div>
      <div><b>Ley equilibrio:</b> ${ley}</div>
      <div><b>Licencia (reproc.):</b> ${p.reprocesable ? "Sí" : "No"}</div>
      <div><b>Evidencia:</b> ${p.evidencia}</div>
    </div>
    <div style="margin-top:6px;font-size:0.78rem;"><b>Acción:</b> ${ETIQUETA_CUADRANTE[cuad] || cuad}</div>
    <div>
      <a class="btn-pdf" href="${p.ficha_pdf}" target="_blank" rel="noopener">📄 Ficha PDF</a>
      <button class="btn-pdf btn-sec" onclick="seleccionarCola('${p.cola_id}', true)">🛰️ Zoom Satélite</button>
    </div>
  `;

  renderizarValidadorVivo(p);
  renderizarRankingBarras();
}

function recalcularPesosYMatriz() {
  const rawI = Number(document.getElementById("w-impacto").value);
  const rawP = Number(document.getElementById("w-poblacion").value);
  const rawA = Number(document.getElementById("w-agua").value);
  const suma = rawI + rawP + rawA || 1;

  const wI = rawI / suma, wP = rawP / suma, wA = rawA / suma;
  document.getElementById("val-w-impacto").textContent = `${Math.round(wI * 100)}%`;
  document.getElementById("val-w-poblacion").textContent = `${Math.round(wP * 100)}%`;
  document.getElementById("val-w-agua").textContent = `${Math.round(wA * 100)}%`;

  const uR = datos.metadata.cuadrantes_cfg.umbral_riesgo_alto;
  const uL = datos.metadata.cuadrantes_cfg.umbral_ley_equilibrio_favorable_g_t;

  datos.colas.features.forEach((f) => {
    const p = f.properties;
    const r = wI * p.pct_I + wP * p.pct_poblacion + wA * p.pct_agua_quieta;
    p.R_i_actual = Number(r.toFixed(4));
    const riesgoAlto = r >= uR;
    const leyFav = p.ley_equilibrio_g_t !== null && p.ley_equilibrio_g_t <= uL;
    if (riesgoAlto && leyFav && p.reprocesable) p.cuadrante_actual = "remediar_y_reprocesar";
    else if (riesgoAlto) p.cuadrante_actual = "remediar_con_fondos_publicos";
    else if (!riesgoAlto && leyFav && p.reprocesable) p.cuadrante_actual = "reprocesar_solo_con_licencia";
    else p.cuadrante_actual = "vigilar";
  });

  // Actualiza mapa, ranking y matriz en vivo
  renderizarColas();
  renderizarRankingBarras();
  dibujarMatrizCuadrantes(uR, uL);
  if (colaSeleccionadaId) seleccionarCola(colaSeleccionadaId, false);
}

function renderizarRankingBarras() {
  const top8 = [...datos.colas.features]
    .sort((a, b) => (b.properties.R_i_actual ?? b.properties.R_i) - (a.properties.R_i_actual ?? a.properties.R_i))
    .slice(0, 8);

  let html = "";
  top8.forEach((f, idx) => {
    const p = f.properties;
    const r = p.R_i_actual ?? p.R_i;
    const activo = p.cola_id === colaSeleccionadaId ? "activo" : "";
    const color = colorPorRiesgo(r);
    html += `
      <div class="rank-item ${activo}" onclick="seleccionarCola('${p.cola_id}', true)">
        <div class="rank-top">
          <span><span class="rank-num">${idx + 1}</span><b>${p.cola_id}</b></span>
          <span>R = <b>${r.toFixed(2)}</b></span>
        </div>
        <div class="rank-bar-bg"><div class="rank-bar-fill" style="width:${Math.max(8, r * 100)}%;background:${color}"></div></div>
      </div>
    `;
  });
  document.getElementById("ranking-barras").innerHTML = html;
}

function renderizarListaMuestreo() {
  const sitios = datos.colas.features.filter((f) => f.properties.prioridad_muestreo);
  let html = "";
  sitios.forEach((f, idx) => {
    const p = f.properties;
    const rol = idx < 5 ? "Prioritario" : "Control";
    html += `
      <div class="rank-item" onclick="seleccionarCola('${p.cola_id}', true)">
        <div class="rank-top">
          <span><b>${p.cola_id}</b> <small>(${p.fuente_poligono})</small></span>
          <span class="badge ${idx < 5 ? 'badge-rojo' : 'badge-info'}">${rol}</span>
        </div>
      </div>
    `;
  });
  document.getElementById("lista-muestreo").innerHTML = html;
}

function dibujarMatrizCuadrantes(uR, uL) {
  const svg = document.getElementById("matriz-svg");
  const W = 340, H = 215, pad = 28;
  const maxLey = Math.max(1.0, ...datos.colas.features.map((f) => f.properties.ley_equilibrio_g_t || 0.5)) * 1.1;

  const mapX = (ley) => pad + ((ley ?? maxLey) / maxLey) * (W - 2 * pad);
  const mapY = (r) => H - pad - r * (H - 2 * pad);
  const xCut = mapX(uL), yCut = mapY(uR);

  let html = `
    <line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="#94a3b8" />
    <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${H - pad}" stroke="#94a3b8" />
    <line x1="${xCut}" y1="${pad}" x2="${xCut}" y2="${H - pad}" stroke="#cbd5e1" stroke-dasharray="4 3" />
    <line x1="${pad}" y1="${yCut}" x2="${W - pad}" y2="${yCut}" stroke="#cbd5e1" stroke-dasharray="4 3" />
    <text x="${pad + 3}" y="${pad + 9}" font-size="8.5" fill="#0f766e">Remediar + Reproc.</text>
    <text x="${xCut + 3}" y="${pad + 9}" font-size="8.5" fill="#b91c1c">Fondos públicos</text>
    <text x="${pad + 3}" y="${H - pad - 5}" font-size="8.5" fill="#0369a1">Solo c/ licencia</text>
    <text x="${xCut + 3}" y="${H - pad - 5}" font-size="8.5" fill="#64748b">Vigilar</text>
  `;

  datos.colas.features.forEach((f) => {
    const p = f.properties;
    const cx = mapX(p.ley_equilibrio_g_t), cy = mapY(p.R_i_actual);
    const esSel = p.cola_id === colaSeleccionadaId;
    const color = colorPorRiesgo(p.R_i_actual);
    html += `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${esSel ? 6.5 : 4.5}" fill="${color}" stroke="${esSel ? '#0f172a' : '#fff'}" stroke-width="1.5" style="cursor:pointer" onclick="seleccionarCola('${p.cola_id}', true)"><title>${p.cola_id}: R=${p.R_i_actual}</title></circle>`;
  });
  svg.innerHTML = html;
}

function renderizarPanelConsumo() {
  const peces = datos.peces_hg || [];
  let html = "";
  peces.forEach((pz) => {
    const umbral = pz.gremio_trofico === "depredador" ? 1.0 : 0.5;
    const pct = Math.min(100, (pz.hg_mg_kg_ph / 2.0) * 100);
    const color = pz.hg_mg_kg_ph > umbral ? "#dc2626" : (pz.hg_mg_kg_ph >= umbral * 0.5 ? "#eab308" : "#16a34a");
    html += `
      <div class="pez-row">
        <div class="pez-head">
          <span><b>${pz.especie}</b> <small>(${pz.gremio_trofico})</small></span>
          <b>${pz.hg_mg_kg_ph.toFixed(2)} mg/kg</b>
        </div>
        <div class="pez-bar-bg"><div class="pez-bar-fill" style="width:${Math.max(4, pct)}%;background:${color}"></div></div>
      </div>
    `;
  });
  document.getElementById("grafico-peces").innerHTML = html || "<p class='ayuda'>Sin datos de peces.</p>";

  const medidos = datos.tramos.features.filter((f) => f.properties.evidencia_semaforo === "medido").length;
  const sinDato = datos.tramos.features.length - medidos;
  document.getElementById("resumen-semaforo-tramos").innerHTML =
    `Tramos con evidencia medida: <b>${medidos}</b> (Río Beni - Rurrenabaque) · ` +
    `Tramos sin dato local (<b>lila discontinuo / prioridad de muestreo</b>): <b>${sinDato}</b>.`;
}

function copiarMensajeRadio() {
  const texto =
    "Cuenca Río Beni (Ref. Loayza 2026): No depredadores (Pacú, Tambaquí, Sábalo) en VERDE (<0.2 mg/kg); depredadores como Blanquillo en ROJO (1.9 mg/kg).\n" +
    "Tramos de Tipuani-Mapiri-Kaka sin muestreo local (prioridad de muestreo).\n" +
    datos.metadata.mensaje_comunitario;
  navigator.clipboard.writeText(texto).then(() => {
    document.getElementById("msg-copiado").textContent = "¡Copiado!";
    setTimeout(() => (document.getElementById("msg-copiado").textContent = ""), 2500);
  });
}

function renderizarValidadorVivo(p) {
  document.getElementById("panel-validador-vivo").innerHTML = `
    <div style="font-size:0.8rem;margin-bottom:8px;">
      Sitio activo: <b>${p.cola_id}</b> · Estado: <b>${p.validado_en_vivo ? "Verificado en campo" : "Pendiente verificación"}</b>
    </div>
    <button class="btn-pdf" onclick="simularValidacionCampo('${p.cola_id}', true)">✅ Confirmar + Licencia Ambiental</button>
    <button class="btn-pdf btn-sec" onclick="simularValidacionCampo('${p.cola_id}', false)">⚠️ Confirmar sin Licencia</button>
  `;
}

function simularValidacionCampo(colaId, conLicencia) {
  const feat = datos.colas.features.find((f) => f.properties.cola_id === colaId);
  if (!feat) return;
  feat.properties.validado_en_vivo = true;
  feat.properties.evidencia = "medido";
  feat.properties.reprocesable = conLicencia;
  recalcularPesosYMatriz();
  seleccionarCola(colaId, false);
}

iniciar();
