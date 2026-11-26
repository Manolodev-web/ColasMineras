"""Generador ligero de fichas PDF por sitio (sin dependencias externas)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Iterable


def _escapar_pdf_texto(texto: str) -> str:
    """Escapa caracteres especiales para strings PDF (WinAnsi/ASCII seguro)."""
    reemplazos = {
        "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
        "ñ": "n", "Ñ": "N", "°": " deg", "–": "-", "—": "-",
    }
    limpio = texto
    for k, v in reemplazos.items():
        limpio = limpio.replace(k, v)
    limpio = limpio.encode("ascii", "replace").decode("ascii")
    return limpio.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def escribir_pdf_simple(ruta_pdf: Path, lineas: Iterable[tuple[str, int, bool]]) -> Path:
    """Escribe un PDF 1.4 válido de una página (Carta) con texto formateado."""
    contenido = ["BT"]
    y = 750
    for texto, size, negrita in lineas:
        fuente = "/F2" if negrita else "/F1"
        contenido.append(f"{fuente} {size} Tf")
        contenido.append(f"50 {y} Td")
        contenido.append(f"({_escapar_pdf_texto(texto)}) Tj")
        # Resetear matriz de texto para posicionamiento absoluto simple en la siguiente línea
        contenido.append(f"-50 {-y} Td")
        y -= int(size * 1.55)
        if y < 50:
            break
    contenido.append("ET")
    stream_bytes = "\n".join(contenido).encode("ascii")

    objetos = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >> endobj\n",
        f"4 0 obj << /Length {len(stream_bytes)} >> stream\n".encode("ascii") + stream_bytes + b"\nendstream endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"6 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> endobj\n",
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objetos:
        offsets.append(len(pdf))
        pdf.extend(obj)

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objetos) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer << /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )

    ruta_pdf.parent.mkdir(parents=True, exist_ok=True)
    ruta_pdf.write_bytes(bytes(pdf))
    return ruta_pdf


def generar_fichas_pdf(
    ruta_gpkg: Path | str,
    carpeta_web_fichas: Path | str | None = None,
) -> list[Path]:
    """Genera una ficha PDF pública por cada cola en `ranking`."""
    if carpeta_web_fichas is None:
        carpeta_web_fichas = Path(__file__).resolve().parents[2] / "web" / "fichas"
    out_dir = Path(carpeta_web_fichas)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(ruta_gpkg))
    try:
        filas = conn.execute(
            """
            SELECT c.cola_id, c.tipo_pasivo, c.area_m2, c.altura_m, c.pendiente_media_deg,
                   c.hand_m, c.en_cuadricula_minera, c.evidencia, c.sintetico,
                   r.I_p50, r.I_p10, r.I_p90, r.prob_top_k, r.es_prioritaria,
                   r.R_i, r.ley_equilibrio_g_t, r.reprocesable, r.cuadrante, r.prioridad_muestreo
            FROM colas_candidatas c
            JOIN ranking r ON c.cola_id = r.cola_id
            ORDER BY r.R_i DESC, c.cola_id
            """
        ).fetchall()
    finally:
        conn.close()

    generados: list[Path] = []
    for row in filas:
        (
            cid, tipo, area, alt, pend, hand, en_cuad, evid, sint,
            i50, i10, i90, p_topk, es_prio, r_i, ley_eq, reproc, cuad, prio_muestreo
        ) = row

        lineas = [
            (f"ALGATECH - FICHA DE SITIO: {cid}", 16, True),
            ("DESAFIO ORO-4.2 | Capa publica (sin datos personales)", 10, False),
        ]
        if int(sint) == 1:
            lineas.append(("*** AVISO: DATOS SIMULADOS PARA DEMOSTRACION (sintetico=true) ***", 11, True))
        lineas.extend(
            [
                ("", 8, False),
                ("1. CARACTERISTICAS DEL PASIVO", 12, True),
                (f"   Tipo de pasivo: {tipo}", 10, False),
                (f"   Area estimada: {area:.1f} m2 | Altura: {alt if alt is not None else 'N/D'} m", 10, False),
                (f"   Pendiente media: {pend} deg | HAND: {hand} m", 10, False),
                (f"   En cuadricula minera (AJAM): {'Si' if en_cuad else 'No'}", 10, False),
                (f"   Nivel de evidencia: {evid}", 10, False),
                ("", 8, False),
                ("2. ATRIBUCION HIDROLOGICA E INCERTIDUMBRE (500 sorteos Monte Carlo)", 12, True),
                (f"   Indice de impacto relativo I (mediana p50): {i50:.2f}", 10, False),
                (f"   Rango de incertidumbre (p10 - p90): [{i10:.2f}, {i90:.2f}]", 10, False),
                (f"   Estabilidad en top-k: {p_topk * 100:.1f}% ({'Prioritaria >=80%' if es_prio else 'No alcanza 80%'})", 10, False),
                ("", 8, False),
                ("3. PRIORIZACION, LEY DE EQUILIBRIO Y ACCION", 12, True),
                (f"   Indice compuesto de riesgo R_i: {r_i:.3f}", 10, False),
                (f"   Ley de equilibrio estimada: {ley_eq:.3f} g Au/t" if ley_eq is not None else "   Ley de equilibrio: N/D", 10, False),
                (f"   Licencia ambiental registrada (reprocesable): {'Si' if reproc else 'No'}", 10, False),
                (f"   Cuadrante sugerido: {cuad}", 10, False),
                (f"   Prioridad de muestreo: {'SI - Incluir en campana' if prio_muestreo else 'No'}", 10, False),
                ("", 8, False),
                ("Nota: Todo resultado es un indice relativo, no una concentracion de Hg.", 9, False),
            ]
        )
        ruta_pdf = out_dir / f"{cid}.pdf"
        escribir_pdf_simple(ruta_pdf, lineas)
        generados.append(ruta_pdf)

    return generados
