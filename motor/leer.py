"""Lectura de PDF: texto nativo por página, OCR para los escaneos e imágenes para la interfaz."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from . import ocr as _ocr

MIN_UTIL = 40          # menos caracteres útiles que esto: la página es un escaneo
DPI_VISTA = 110        # imagen para la interfaz
DPI_OCR = 300          # imagen para Tesseract


def _utiles(texto: str) -> int:
    """Cantidad de caracteres alfanuméricos."""
    return sum(1 for c in texto if c.isalnum())


def _limpiar(texto: str) -> str:
    texto = texto.replace("\x00", "").replace("­", "")
    texto = re.sub(r"[ \t]+\n", "\n", texto)
    return texto.strip()


def leer_pdf(ruta_pdf, carpeta_caso, ocr: bool = True, desde: int = 1) -> list[dict]:
    """Lee un PDF y devuelve una lista de páginas.

    Cada página: {"n", "archivo", "origen" (texto|ocr|vacia), "confianza_ocr",
    "tipo" (None hasta clasificar), "imagen" (relativa a carpeta_caso), "texto"}.
    `desde` es el número de la primera página (para expedientes con varios PDF).
    El PNG de TODAS las páginas se guarda en carpeta_caso/paginas/pNNN.png.
    """
    ruta_pdf = Path(ruta_pdf)
    carpeta = Path(carpeta_caso)
    dir_png = carpeta / "paginas"
    dir_png.mkdir(parents=True, exist_ok=True)
    usar_ocr = bool(ocr) and _ocr.ocr_disponible()[0]

    paginas: list[dict] = []
    with fitz.open(ruta_pdf) as doc:
        for i, pag in enumerate(doc):
            n = desde + i
            nombre_png = f"p{n:03d}.png"
            pag.get_pixmap(dpi=DPI_VISTA, colorspace=fitz.csRGB).save(str(dir_png / nombre_png))

            texto = _limpiar(pag.get_text())
            origen, conf = "texto", None
            if _utiles(texto) < MIN_UTIL:
                nativo = texto
                texto, origen = nativo, ("texto" if _utiles(nativo) else "vacia")
                if usar_ocr:
                    fd, tmp = tempfile.mkstemp(suffix=".png", dir=str(dir_png))
                    os.close(fd)
                    try:
                        pag.get_pixmap(dpi=DPI_OCR, colorspace=fitz.csGRAY).save(tmp)
                        t_ocr, c_ocr = _ocr.ocr_imagen(tmp)
                    finally:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
                    t_ocr = _limpiar(t_ocr)
                    if _utiles(t_ocr) >= 10:
                        texto = (nativo + "\n" + t_ocr).strip() if _utiles(nativo) else t_ocr
                        origen, conf = "ocr", c_ocr
            paginas.append({
                "n": n,
                "archivo": ruta_pdf.name,
                "origen": origen,
                "confianza_ocr": conf,
                "tipo": None,
                "imagen": f"paginas/{nombre_png}",
                "texto": texto,
            })
    return paginas
