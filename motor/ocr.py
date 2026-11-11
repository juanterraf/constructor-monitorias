"""OCR local con Tesseract, opcional. Si no está, nada se rompe: se avisa."""
from __future__ import annotations

import shutil
from pathlib import Path

_CACHE: dict = {}

# Lugares habituales en Windows si el ejecutable no está en el PATH.
_RUTAS_WINDOWS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _preparar_pytesseract():
    """Devuelve el módulo pytesseract con la ruta del ejecutable resuelta, o None."""
    try:
        import pytesseract
    except Exception:
        return None
    if shutil.which("tesseract") is None:
        for r in _RUTAS_WINDOWS:
            if Path(r).exists():
                pytesseract.pytesseract.tesseract_cmd = r
                break
    return pytesseract


def ocr_disponible() -> tuple[bool, str]:
    """(sí/no, motivo). Se calcula una vez por proceso."""
    if "disp" in _CACHE:
        return _CACHE["disp"]
    res: tuple[bool, str]
    try:
        import PIL  # noqa: F401
    except Exception:
        res = (False, "Falta Pillow")
        _CACHE["disp"] = res
        return res
    pt = _preparar_pytesseract()
    if pt is None:
        res = (False, "Falta el paquete pytesseract")
    else:
        try:
            ver = str(pt.get_tesseract_version())
            idiomas = set(pt.get_languages(config=""))
            if "spa" in idiomas:
                res = (True, f"Tesseract {ver} con idioma spa")
            elif idiomas:
                res = (True, f"Tesseract {ver} sin spa (se usará otro idioma)")
            else:
                res = (False, "Tesseract no tiene idiomas instalados")
        except Exception:
            res = (False, "No se encontró el programa Tesseract")
    _CACHE["disp"] = res
    return res


def _preprocesar(img):
    from PIL import Image, ImageFilter, ImageOps

    g = ImageOps.grayscale(img)
    # Si la imagen es chica, se agranda: Tesseract rinde mejor con letra de ~30 px.
    if max(g.size) < 1800:
        f = 2
        g = g.resize((g.width * f, g.height * f), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)
    g = g.filter(ImageFilter.MedianFilter(3))
    return g


def ocr_imagen(ruta_png, idioma: str = "spa") -> tuple[str, float]:
    """Texto de una imagen y confianza media de las palabras (0 a 1).

    Si no hay Tesseract devuelve ("", 0.0).
    """
    ok, _ = ocr_disponible()
    if not ok:
        return "", 0.0
    pt = _preparar_pytesseract()
    from PIL import Image

    try:
        with Image.open(ruta_png) as im:
            img = _preprocesar(im)
        try:
            datos = pt.image_to_data(img, lang=idioma, config="--psm 6",
                                     output_type=pt.Output.DICT)
        except pt.TesseractError:
            datos = pt.image_to_data(img, lang="eng", config="--psm 6",
                                     output_type=pt.Output.DICT)
    except Exception:
        return "", 0.0

    lineas: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for i, palabra in enumerate(datos["text"]):
        palabra = (palabra or "").strip()
        if not palabra:
            continue
        try:
            c = float(datos["conf"][i])
        except (TypeError, ValueError):
            c = -1
        if c >= 0:
            confs.append(c)
        clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
        lineas.setdefault(clave, []).append(palabra)
    texto = "\n".join(" ".join(p) for p in lineas.values())
    conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return texto, round(max(0.0, min(1.0, conf)), 3)
