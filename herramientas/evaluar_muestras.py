"""Corre la detección sobre una carpeta de PDF y muestra, por archivo, solo conteos.

Uso:  python herramientas/evaluar_muestras.py <carpeta> [--sin-ocr] [--temp <carpeta>]

No imprime valores ni citas: organismo, páginas por tipo y por origen, y por campo la cantidad de
candidatos y la confianza máxima. Copia cada PDF a una carpeta temporal fuera del repositorio
para guardar ahí las imágenes de las páginas.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from motor import detectar as det  # noqa: E402
from motor import leer, ocr  # noqa: E402


def evaluar_pdf(pdf: Path, trabajo: Path, usar_ocr: bool) -> dict:
    copia = trabajo / pdf.name
    shutil.copy2(pdf, copia)
    caso = trabajo / ("caso-" + pdf.stem[:20].replace(" ", "_"))
    paginas = leer.leer_pdf(copia, caso, ocr=usar_ocr)
    det.clasificar_paginas(paginas)
    res = det.detectar(paginas)
    return {"paginas": paginas, "res": res}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("carpeta")
    ap.add_argument("--sin-ocr", action="store_true")
    ap.add_argument("--temp", default=None, help="carpeta de trabajo (fuera del repositorio)")
    a = ap.parse_args()

    pdfs = sorted(Path(a.carpeta).rglob("*.pdf"))
    if not pdfs:
        print("No hay PDF en esa carpeta.")
        return 1
    trabajo = Path(a.temp) if a.temp else Path(tempfile.mkdtemp(prefix="evaluar_monitorias_"))
    trabajo.mkdir(parents=True, exist_ok=True)
    try:
        trabajo.resolve().relative_to(RAIZ)
        print("La carpeta de trabajo no puede estar dentro del repositorio.")
        return 2
    except ValueError:
        pass
    ok, motivo = ocr.ocr_disponible()
    usar_ocr = ok and not a.sin_ocr
    print(f"OCR: {'sí' if usar_ocr else 'no'} ({motivo})")

    campos_orden = [f"demanda.{x}" for x in det.CAMPOS_DEMANDA] + [f"boleta.{x}" for x in det.CAMPOS_BOLETA]
    resumen: Counter = Counter()
    for i, pdf in enumerate(pdfs, 1):
        info = evaluar_pdf(pdf, trabajo, usar_ocr)
        paginas, res = info["paginas"], info["res"]
        tipos = Counter(p["tipo"] for p in paginas)
        origenes = Counter(p["origen"] for p in paginas)
        o = res["organismo"]
        print(f"\n[{i:02d}] {len(paginas)} págs · organismo: {o['valor'] or 'no consta'} ({o['confianza']:.2f})")
        print("     tipos: " + ", ".join(f"{k} {v}" for k, v in sorted(tipos.items()))
              + " · origen: " + ", ".join(f"{k} {v}" for k, v in sorted(origenes.items())))
        linea = []
        for campo in campos_orden:
            cands = res["campos"][campo]["candidatos"]
            if cands:
                resumen[campo] += 1
                linea.append(f"{campo}={len(cands)}/{max(c['confianza'] for c in cands):.2f}")
        print("     " + "  ".join(linea) if linea else "     (sin candidatos)")
    print(f"\nArchivos con al menos un candidato, por campo (de {len(pdfs)}):")
    for campo in campos_orden:
        print(f"  {campo:34s} {resumen[campo]:3d}")
    print(f"\nImágenes y copias en: {trabajo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
