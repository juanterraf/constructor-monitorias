"""Pruebas de lectura y detección. Todos los textos son inventados."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from motor import detectar as det  # noqa: E402
from motor import leer, ocr  # noqa: E402


def pag(n, texto, origen="texto", conf=None):
    return {"n": n, "archivo": "x.pdf", "origen": origen, "confianza_ocr": conf, "tipo": None,
            "imagen": f"paginas/p{n:03d}.png", "texto": texto}


DEMANDA_SAT = """INICIO JUICIO DE APREMIOS.-
Sr. Juez de Cobros y Apremios de turno
Juicio: “Sociedad Aguas del Tucumán S.A.P.E.M. c/ Pérez Juan Carlos s/ Apremios”.

LÓPEZ MARTA ELENA, abogada matrícula N° 1234, Libro N- Folio 390, con domicilio en calle
Falsa N° 100 de esta ciudad, y constituyendo domicilio en casillero Digital N° 27-12345678-0, a V.S.,
respetuosamente digo:
I.- PERSONERIA: soy apoderada de la sociedad Aguas del Tucumán S.A.P.E.M. (SAT SAPEM), CUIT 30-12345678-1.
II.- OBJETO: vengo a entablar acción de cobro ejecutivo en contra de Pérez Juan Carlos, DNI: 12.345.678
y/o quien resulte propietario del inmueble ubicado en Calle Inventada N° 456 de la ciudad de Yerba Buena,
y/o quien resulte usuario, por la suma de pesos ($71.234,56), con más intereses y costas.
III.- FUNDAMENTOS: conforme la Boleta de Deuda N° 11111/2024, base de esta acción.
VII.- PETITORIO: Proveer de conformidad, SERÁ JUSTICIA.-
"""

BOLETA_SAT = """BOLETA DE DEUDA
N° 11111/2024
Certifico que el propietario o usuario del inmueble sito en CALLE INVENTADA N° 456 YERBA BUENA
Sr/a. PÉREZ, JUAN CARLOS ------------- CUIL 20-12345678-6 con domicilio especial/real/social en CALLE INVENTADA N° 456
MATRICULA REGISTRAL T-1 y PADRON CATASTRAL 1 adeuda a Aguas del Tucumán Sociedad Anónima CUIT 30-12345678-1,
por el servicio de agua potable y/o desagües cloacales prestados al inmueble, la suma de $ 71,234.56.
La mencionada deuda se compone por el importe de las facturas a su valor nominal histórico:
Período 8° Mes/2022 $ 1,111.11 Fact. N°: 0010-10000001 Vencimiento 09/09/2022
Período 9° Mes/2022 $ 2,222.22 Fact. N°: 0010-10000002 Vencimiento 11/10/2022
Período 10° Mes/2022 $ 2,333.33 Fact. N°: 0010-10000003 Vencimiento 10/11/2022
TOTAL $ 71,234.56
se extiende la presente boleta de deuda en la ciudad de San Miguel de Tucumán, a los 21 días del mes de OCTUBRE de 2024.
"""

BOLETA_DGR = """DIVISION CONTROL DE COBROS JUDICIALES
- SECCION EMISION DE TITULOS EJECUTIVOS -
CUIT/CUIL: 30123456781
DEUDOR: EMPRESA INVENTADA S.R.L.
DOMICILIO: CALLE FALSA 123
LOCALIDAD: SAN MIGUEL DE TUCUMAN CODIGO POSTAL: 4000
N° DE BOLETA DE DEUDA: BTE/7001/2024 9999/111/CD/2023
IMPUESTO PARA LA SALUD PUBLICA
CONCEPTO DE LA DEUDA: DEUDA AL 20/05/2024
IMPUESTO PARA LA SALUD PUBLICA - SANCION (ANTICIPOS 04 A 12/2021, 01 A 06/2022)
MULTA IMPORTE TOTAL
TOTALES GENERALES 111.111,00 140.000,00
TOTAL GENERAL DE LA DEUDA 140.000,00
San Miguel de Tucumán, Lunes 20 de Mayo de 2024
"""

DEMANDA_DGR = """Abogado M.P. 5151 - Apoderado fiscal
Direccion General de Rentas – Provincia de Tucumán
PROMUEVO DEMANDA DE EJECUCION FISCAL.-
SEÑORA JUEZ DE COBROS Y APREMIOS.-
JUICIO: “PROVINCIA DE TUCUMAN –D.G.R.- C/ EMPRESA INVENTADA S.R.L. S/EJECUCION
FISCAL”.
Fulano de Tal, abogado de la matrícula 5151 Libro: N Folio: 976, con domicilio en calle Otra 960, de esta ciudad,
me presento y digo: I).-PERSONERIA: apoderado de la Dirección General de Rentas.
II).-OBJETO: demanda de ejecución fiscal tendiente al cobro de la suma de PESOS CIENTO CUARENTA MIL ($ 140000 ).
III).- HECHOS: Boleta de Deuda denominada “Cargo Tributario” Nº BTE/7001/2024, por el impuesto IMPUESTO PARA LA SALUD PUBLICA,
correspondiente al Expte. N° 123/2024. Expediente Administrativo Nº 9999/111/CD/2023.
Proveer de conformidad por ser JUSTICIA.
"""

DEMANDA_MUNI = """INICIO DEMANDA
SR. JUEZ CIVIL DE COBROS Y APREMIOS DE TURNO
JUICIO: “MUNICIPALIDAD DE SAN MIGUEL DE TUCUMÁN c/ INVENTADA S.R.L s/ EJECUCIÓN FISCAL”.
MARIO PRUEBA, abogado, Matrícula Profesional N° 6262, FISCAL MUNICIPAL, a V.S. respetuosamente digo:
I. PERSONERÍA soy apoderado general de la Municipalidad de San Miguel de Tucumán.
II. OBJETO: juicio de ejecución fiscal, en contra de INVENTADA S.R.L CUIT N° 30-87654321-0 PADRON MUNICIPAL N° 1 con domicilio
en calle LIBERTAD 100. de esta ciudad, por la suma de $123.456,78 (Pesos Ciento Veintitres Mil).
III. TITULO EJECUTIVO: la BOLETA DE DEUDA CUENTA JUDICIAL N° 20202/2024, períodos 05/2019 al 03/2024 en concepto de
C.I.S.I. (CONTRIBUCIONES QUE INCIDEN SOBRE INMUEBLES). Solicito costas y mandamiento.
"""

PODER = """ESCRITURA NUMERO: CIENTO CINCUENTA. En la Ciudad de San Miguel de Tucumán comparece el señor Fulano,
ante mí, escribana pública adscripta al Registro Notarial. Confiere PODER GENERAL PARA JUICIOS a favor del letrado Mengano.
Actuación notarial. Doy fe.
"""


def campo(res, nombre):
    return res["campos"][nombre]


class Utilidades(unittest.TestCase):
    def test_cuit_valido_e_invalido(self):
        self.assertTrue(det.cuit_valido("20-12345678-6"))
        self.assertTrue(det.cuit_valido("27123456780"))
        self.assertFalse(det.cuit_valido("20-12345678-1"))
        self.assertFalse(det.cuit_valido("123"))
        self.assertFalse(det.cuit_valido("99123456786"))

    def test_montos_argentinos_y_de_boleta(self):
        for entrada, esperado in [("$ 1.234,56", "1234.56"), ("71,234.56", "71234.56"),
                                  ("71.234.56", "71234.56"), ("152580", "152580.00"),
                                  ("1.234", "1234.00"), ("$123.456,78", "123456.78"),
                                  ("2.056.121,11", "2056121.11")]:
            self.assertEqual(det.parse_monto(entrada), esperado, entrada)

    def test_fechas_numericas_y_en_letras(self):
        fs = det.fechas_en(det._plano("Emitida el 20/05/2024 y el 3 de febrero de 2023; 31/02/2024 no existe."))
        self.assertEqual([f[0] for f in fs], ["2024-05-20", "2023-02-03"])

    def test_periodos_rango_numerico_se_expande(self):
        r = det.periodos_en(det._plano("períodos 01/2023 a 06/2023"))
        self.assertEqual(r[0][0], ["2023-01", "2023-02", "2023-03", "2023-04", "2023-05", "2023-06"])

    def test_periodos_rango_en_letras(self):
        r = det.periodos_en(det._plano("correspondiente a enero a marzo de 2025"))
        self.assertEqual(r[0][0], ["2025-01", "2025-02", "2025-03"])
        r = det.periodos_en(det._plano("de noviembre de 2024 a febrero de 2025"))
        self.assertEqual(r[0][0], ["2024-11", "2024-12", "2025-01", "2025-02"])

    def test_periodos_anticipos_y_sueltos(self):
        r = det.periodos_en(det._plano("anticipos 04 a 12/2021"))
        self.assertEqual(len(r[0][0]), 9)
        r = det.periodos_en(det._plano("período 03/2025"))
        self.assertEqual(r[0][0], ["2025-03"])
        r = det.periodos_en(det._plano("período junio de 2025"))
        self.assertEqual(r[0][0], ["2025-06"])

    def test_dia_en_letras_no_es_periodo(self):
        self.assertEqual(det.periodos_en(det._plano("el 20 de mayo de 2024 y vence 20/05/2024")), [])

    def test_periodos_tabla_sat(self):
        r = det.periodos_en(det._plano(BOLETA_SAT))
        self.assertEqual(r[0][0], ["2022-08", "2022-09", "2022-10"])
        self.assertEqual(r[0][1], "periodos-tabla")


class Clasificacion(unittest.TestCase):
    def test_tipos_de_pagina(self):
        ps = det.clasificar_paginas([pag(1, DEMANDA_SAT), pag(2, BOLETA_SAT), pag(3, PODER),
                                     pag(4, BOLETA_DGR), pag(5, "Constancia de inscripción AFIP. Impuestos registrados."),
                                     pag(6, "")])
        self.assertEqual([p["tipo"] for p in ps], ["demanda", "boleta", "poder", "boleta", "otro", "otro"])

    def test_demanda_dgr_y_municipal(self):
        ps = det.clasificar_paginas([pag(1, DEMANDA_DGR), pag(2, DEMANDA_MUNI)])
        self.assertEqual([p["tipo"] for p in ps], ["demanda", "demanda"])

    def test_hoja_de_continuacion_hereda_demanda(self):
        ps = det.clasificar_paginas([pag(1, DEMANDA_SAT),
                                     pag(2, "5) Se tenga presente el diferimiento solicitado y las costas, con más intereses hasta el pago. " * 3)])
        self.assertEqual(ps[1]["tipo"], "demanda")

    def test_organismo_sat_dgr_municipalidad(self):
        r = det.detectar([pag(1, DEMANDA_SAT), pag(2, BOLETA_SAT)])
        self.assertEqual(r["organismo"]["valor"], "SAT")
        r = det.detectar([pag(1, DEMANDA_DGR), pag(2, BOLETA_DGR)])
        self.assertEqual(r["organismo"]["valor"], "DGR")
        r = det.detectar([pag(1, DEMANDA_MUNI)])
        self.assertEqual(r["organismo"]["valor"], "MUNICIPALIDAD")
        self.assertEqual(campo(r, "demanda.ejecutante")["valor"], "Municipalidad de San Miguel de Tucumán")

    def test_organismo_ignora_jurisprudencia_citada(self):
        texto = DEMANDA_SAT + '\nDIFERIMIENTO: Sala 2 in re “Municipalidad de S.M. de Tucumán c/ Gomez s/ ejecución fiscal”, Sala 1 in re “Prov. de Tucumán DGR c/ Pérez s/ ejecución fiscal”.'
        r = det.detectar([pag(1, texto)])
        self.assertEqual(r["organismo"]["valor"], "SAT")
        self.assertEqual(campo(r, "demanda.ejecutante")["valor"], "SAT")

    def test_sin_candidatos_es_null(self):
        r = det.detectar([pag(1, "texto cualquiera sin nada")])
        self.assertIsNone(r["organismo"]["valor"])
        self.assertIsNone(campo(r, "demanda.monto_total")["valor"])


class ReglasDemanda(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = det.detectar([pag(1, DEMANDA_SAT)])

    def test_caratula(self):
        v = campo(self.r, "demanda.caratula")["valor"]
        self.assertTrue(v.startswith("Sociedad Aguas del Tucumán") and v.endswith("s/ Apremios"), v)

    def test_ejecutado_nombre(self):
        self.assertEqual(campo(self.r, "demanda.ejecutado_nombre")["valor"], "Pérez Juan Carlos")

    def test_dni_en_contexto_del_demandado(self):
        self.assertEqual(campo(self.r, "demanda.ejecutado_documento")["valor"], "12345678")

    def test_cuit_del_ejecutante_y_del_letrado_quedan_bajos(self):
        cands = campo(self.r, "demanda.ejecutado_documento")["candidatos"]
        por_valor = {c["valor"]: c["confianza"] for c in cands}
        self.assertLess(por_valor["30123456781"], 0.3)
        self.assertLess(por_valor["27123456780"], 0.3)

    def test_domicilio_del_inmueble_y_no_el_del_letrado(self):
        v = campo(self.r, "demanda.ejecutado_domicilio")["valor"]
        self.assertIn("Inventada", v)

    def test_letrado_y_matricula(self):
        self.assertEqual(campo(self.r, "demanda.letrado_nombre")["valor"], "LÓPEZ MARTA ELENA")
        self.assertEqual(campo(self.r, "demanda.letrado_matricula")["valor"], "1234")

    def test_tomo_folio(self):
        r = det.detectar([pag(1, DEMANDA_SAT + "\nT° 12 F° 345 del Colegio de Abogados. A V.S. respetuosamente.")])
        vals = [c["valor"] for c in campo(r, "demanda.letrado_matricula")["candidatos"]]
        self.assertIn("T°12 F°345", vals)

    def test_monto_total_y_capital(self):
        self.assertEqual(campo(self.r, "demanda.monto_total")["valor"], "71234.56")
        self.assertEqual(campo(self.r, "demanda.monto_capital")["valor"], "71234.56")

    def test_monto_en_letras_y_numero(self):
        r = det.detectar([pag(1, DEMANDA_DGR)])
        self.assertEqual(campo(r, "demanda.monto_total")["valor"], "140000.00")

    def test_numero_de_boleta(self):
        self.assertEqual(campo(self.r, "demanda.boleta_numero")["valor"], "11111/2024")

    def test_expediente_numero_sin_confundir_el_administrativo(self):
        r = det.detectar([pag(1, DEMANDA_DGR)])
        self.assertEqual(campo(r, "demanda.expediente_numero")["valor"], "123/2024")

    def test_matricula_mp_y_concepto_dgr(self):
        r = det.detectar([pag(1, DEMANDA_DGR)])
        self.assertEqual(campo(r, "demanda.letrado_matricula")["valor"], "5151")
        self.assertEqual(campo(r, "demanda.concepto")["valor"], "IMPUESTO PARA LA SALUD PUBLICA")

    def test_periodos_y_concepto_municipal(self):
        r = det.detectar([pag(1, DEMANDA_MUNI)])
        per = campo(r, "demanda.periodos")["valor"]
        self.assertEqual((per[0], per[-1], len(per)), ("2019-05", "2024-03", 59))
        self.assertTrue(campo(r, "demanda.concepto")["valor"].startswith("C.I.S.I."))
        self.assertEqual(campo(r, "demanda.ejecutado_documento")["valor"], "30876543210")

    def test_cada_candidato_tiene_los_datos_del_contrato(self):
        for v in self.r["campos"].values():
            for c in v["candidatos"]:
                self.assertEqual(set(c), {"valor", "pagina", "cita", "origen", "confianza", "regla"})
                self.assertTrue(0 <= c["confianza"] <= 1)
            if v["candidatos"]:
                self.assertEqual(v["valor"], v["candidatos"][0]["valor"])
            self.assertFalse(v["confirmado"])


class ReglasBoleta(unittest.TestCase):
    def test_boleta_sat(self):
        r = det.detectar([pag(1, DEMANDA_SAT), pag(2, BOLETA_SAT)])
        self.assertEqual(campo(r, "boleta.boleta_numero")["valor"], "11111/2024")
        self.assertEqual(campo(r, "boleta.monto_total")["valor"], "71234.56")
        self.assertEqual(campo(r, "boleta.ejecutado_nombre")["valor"], "PÉREZ, JUAN CARLOS")
        self.assertEqual(campo(r, "boleta.ejecutado_documento")["valor"], "20123456786")
        self.assertEqual(campo(r, "boleta.boleta_fecha")["valor"], "2024-10-21")
        self.assertEqual(campo(r, "boleta.periodos")["valor"], ["2022-08", "2022-09", "2022-10"])
        self.assertEqual(campo(r, "boleta.concepto")["valor"], "Servicio de agua potable y desagües cloacales")

    def test_cuit_con_digito_invalido_baja_la_confianza(self):
        bueno = det.detectar([pag(1, BOLETA_SAT)])
        malo = det.detectar([pag(1, BOLETA_SAT.replace("20-12345678-6", "20-12345678-1"))])
        cb = [c for c in campo(bueno, "boleta.ejecutado_documento")["candidatos"] if c["valor"] == "20123456786"][0]
        cm = [c for c in campo(malo, "boleta.ejecutado_documento")["candidatos"] if c["valor"] == "20123456781"][0]
        self.assertEqual(cb["regla"], "cuit-valido")
        self.assertEqual(cm["regla"], "cuit-dv-invalido")
        self.assertLess(cm["confianza"], cb["confianza"] / 2)

    def test_boleta_dgr(self):
        r = det.detectar([pag(1, BOLETA_DGR)])
        self.assertEqual(campo(r, "boleta.ejecutado_nombre")["valor"], "EMPRESA INVENTADA S.R.L.")
        self.assertEqual(campo(r, "boleta.ejecutado_documento")["valor"], "30123456781")
        self.assertEqual(campo(r, "boleta.ejecutado_domicilio")["valor"], "CALLE FALSA 123, SAN MIGUEL DE TUCUMAN")
        self.assertEqual(campo(r, "boleta.boleta_numero")["valor"], "BTE/7001/2024")
        self.assertEqual(campo(r, "boleta.boleta_fecha")["valor"], "2024-05-20")
        self.assertEqual(campo(r, "boleta.monto_capital")["valor"], "111111.00")
        self.assertEqual(campo(r, "boleta.monto_total")["valor"], "140000.00")
        self.assertEqual(len(campo(r, "boleta.periodos")["valor"]), 15)

    def test_suma_de_dos_boletas(self):
        r = det.detectar([pag(1, BOLETA_DGR), pag(2, BOLETA_DGR.replace("140.000,00", "10.000,00"))])
        valores = [c["valor"] for c in campo(r, "boleta.monto_total")["candidatos"]]
        self.assertIn("150000.00", valores)

    def test_confianza_se_multiplica_por_la_del_ocr(self):
        a = det.detectar([pag(1, BOLETA_DGR, "texto")])
        b = det.detectar([pag(1, BOLETA_DGR, "ocr", 0.5)])
        ca = campo(a, "boleta.monto_total")["candidatos"][0]
        cb = campo(b, "boleta.monto_total")["candidatos"][0]
        self.assertEqual(cb["origen"], "ocr")
        self.assertAlmostEqual(cb["confianza"], ca["confianza"] * 0.5, places=2)

    def test_ejecutado_en_boleta_municipal(self):
        texto = ("DIM SAN MIGUEL DE TUCUMAN, 18/03/2024\nDIRECCIÓN DE INGRESOS MUNICIPALES\n"
                 "INVENTADA SRL, CUIT N° 30876543210, con domicilio fiscal en LIBERTAD 100 Padrón Municipal N° 1 adeuda a la\n"
                 "Municipalidad de San Miguel de Tucumán, la suma de PESOS: CIENTO CUARENTA\n"
                 "2019/005 C.I.S.I. 10/09/2019 1000.00 2000.00 3000.00\n2019/006 C.I.S.I. 11/11/2019 1000.00 2100.00 3100.00\n"
                 "Deuda actualizada al 18/03/2024 TOTALES: $ 50000.10 $ 40000.20 $ 123456.78\n")
        r = det.detectar([pag(1, texto)])
        self.assertEqual(r["organismo"]["valor"], "MUNICIPALIDAD")
        self.assertEqual(campo(r, "boleta.monto_capital")["valor"], "50000.10")
        self.assertEqual(campo(r, "boleta.monto_total")["valor"], "123456.78")
        self.assertEqual(campo(r, "boleta.boleta_fecha")["valor"], "2024-03-18")
        self.assertEqual(campo(r, "boleta.periodos")["valor"], ["2019-05", "2019-06"])
        self.assertEqual(campo(r, "boleta.ejecutado_documento")["valor"], "30876543210")


class Lectura(unittest.TestCase):
    def test_pdf_con_pagina_de_texto_y_pagina_de_imagen(self):
        import fitz
        ok, motivo = ocr.ocr_disponible()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # Página de solo imagen: se dibuja el texto con Pillow.
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (1400, 500), "white")
            d = ImageDraw.Draw(img)
            try:
                fuente = ImageFont.truetype("arial.ttf", 56)
            except OSError:
                fuente = ImageFont.load_default()
            d.text((60, 120), "BOLETA DE DEUDA", fill="black", font=fuente)
            d.text((60, 260), "TOTAL GENERAL 12345", fill="black", font=fuente)
            png = tmp / "escaneo.png"
            img.save(png)
            doc = fitz.open()
            p1 = doc.new_page()
            p1.insert_text((72, 100), "Sr. Juez de Cobros y Apremios. Esta es una página con texto nativo suficiente para leer.", fontsize=11)
            p2 = doc.new_page()
            p2.insert_image(p2.rect, filename=str(png))
            pdf = tmp / "prueba.pdf"
            doc.save(str(pdf))
            doc.close()

            caso = tmp / "caso"
            paginas = leer.leer_pdf(pdf, caso, ocr=True)
            self.assertEqual(len(paginas), 2)
            self.assertEqual(paginas[0]["origen"], "texto")
            self.assertIsNone(paginas[0]["confianza_ocr"])
            for p in paginas:
                self.assertTrue((caso / p["imagen"]).exists(), p["imagen"])
            if not ok:
                self.assertIn(paginas[1]["origen"], ("vacia", "texto"))
                self.skipTest(f"Sin OCR: {motivo}")
            self.assertEqual(paginas[1]["origen"], "ocr")
            self.assertGreater(paginas[1]["confianza_ocr"], 0.5)
            self.assertIn("deuda", paginas[1]["texto"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
