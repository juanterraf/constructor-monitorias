"""Pruebas de las mejoras de cotejo, detección y chequeos. Datos inventados. Correr: python -m unittest tests.test_mejoras -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from motor import chequeos, cotejo, organismos  # noqa: E402
from motor import detectar as det  # noqa: E402
from test_reglas import CONFIG, caso_base  # noqa: E402
import servidor  # noqa: E402

# Boleta inventada con los defectos de OCR que se vieron en una real
BOLETA_OCR = """N 77123/2025
Sr/a. GOMEZ, ANA MARIA-=====-=--CUI1L27-12345678-9 con do-
123456ladeuda a Aguas
pas Lec o tp eri aan A pe E CUIT 30-70861788-8, por el servicio de
11* mes/2020 $ 100.00
01° Mes/2021 $ 964.76
06" Mes/2023 $ 12.00
08* Mes/2031 $ 1.00
CAPITAL $ 1,000.00 INTERESES $ 500.50 TOTAL$ 1,500.50
- TOTAL GENERAL DE LA DEUDA $ 1,500.50 -
a los 06 días del mes de NOVIEMBRE de 2025.
"""


def detectar_boleta(texto=BOLETA_OCR):
    p = {"n": 1, "archivo": "x.pdf", "origen": "ocr", "confianza_ocr": 0.8, "tipo": "boleta",
         "imagen": "paginas/p001.png", "texto": texto}
    return det.detectar([p])["campos"]


def filas(**cambios):
    return {f["campo"]: f for f in cotejo.cotejar(caso_base(**cambios)["campos"])}


class TestCotejoNuevo(unittest.TestCase):
    def test_solo_boleta(self):
        f = filas(**{"demanda.boleta_fecha": None})["boleta_fecha"]
        self.assertEqual(f["resultado"], "SOLO BOLETA")

    def test_falta_cuando_falta_en_la_boleta(self):
        self.assertEqual(filas(**{"boleta.boleta_numero": None})["boleta_numero"]["resultado"], "FALTA")

    def test_dni_contra_cuil(self):
        f = filas(**{"demanda.ejecutado_documento": "11.111.111"})["ejecutado_documento"]
        self.assertEqual(f["resultado"], "COINCIDE")
        f = filas(**{"demanda.ejecutado_documento": "11111112"})["ejecutado_documento"]
        self.assertEqual(f["resultado"], "DIFIERE")

    def test_aviso_de_digito_verificador(self):
        self.assertFalse(cotejo.cuit_valido("27123456789"))
        f = filas(**{"boleta.ejecutado_documento": "27123456789", "demanda.ejecutado_documento": "12345678"})["ejecutado_documento"]
        self.assertEqual(f["resultado"], "COINCIDE")
        self.assertIn("dígito verificador", f["detalle"])

    def test_ejecutante_por_organismo(self):
        f = filas(**{"demanda.ejecutante": "SAT", "boleta.ejecutante": "Sociedad Aguas del Tucumán S.A.P.E.M."})["ejecutante"]
        self.assertEqual(f["resultado"], "COINCIDE")
        f = filas(**{"demanda.ejecutante": "DGR"})["ejecutante"]
        self.assertEqual(f["resultado"], "DIFIERE")

    def test_ejecutante_municipalidad_compara_municipio(self):
        base = {"demanda.ejecutante": "Municipalidad de Yerba Buena", "boleta.ejecutante": "Municipalidad de Yerba Buena"}
        self.assertEqual(filas(**base)["ejecutante"]["resultado"], "COINCIDE")
        base["boleta.ejecutante"] = "Municipalidad de Lules"
        self.assertEqual(filas(**base)["ejecutante"]["resultado"], "DIFIERE")

    def test_capital_reclamado_es_el_total_de_la_boleta(self):
        f = filas(**{"demanda.monto_capital": "1500.00", "boleta.monto_capital": "1000.00", "boleta.monto_total": "1500.00"})["monto_capital"]
        self.assertEqual(f["resultado"], "COINCIDE")
        self.assertIn("total de la boleta", f["detalle"])
        f = filas(**{"demanda.monto_capital": "999.00", "boleta.monto_capital": "1000.00", "boleta.monto_total": "1500.00"})["monto_capital"]
        self.assertEqual(f["resultado"], "DIFIERE")


class TestDetectarNuevo(unittest.TestCase):
    def test_cuil_pegado_a_la_etiqueta(self):
        c = detectar_boleta()["boleta.ejecutado_documento"]
        self.assertEqual(c["valor"], "27123456789")
        self.assertEqual(c["candidatos"][0]["regla"], "cuit-dv-invalido")
        self.assertGreater(c["candidatos"][0]["confianza"], 0.4)  # baja poco

    def test_cuit_de_la_sat_es_ejecutante_y_no_documento(self):
        campos = detectar_boleta()
        self.assertEqual(campos["boleta.ejecutante"]["valor"], "SAT")
        self.assertIn("cuit-ejecutante", [x["regla"] for x in campos["boleta.ejecutante"]["candidatos"]])
        self.assertNotIn("30708617888", [x["valor"] for x in campos["boleta.ejecutado_documento"]["candidatos"]])
        self.assertEqual(organismos.CUIT_EJECUTANTES["30708617888"], "SAT")

    def test_varios_cuit_prefiere_persona(self):
        txt = "Sr/a. GOMEZ, ANA MARIA CUIT 30-11111111-8 y CUIT 20-22222222-3 contra el deudor"
        cands = detectar_boleta(txt)["boleta.ejecutado_documento"]["candidatos"]
        self.assertTrue(cands[0]["valor"].startswith("20"))

    def test_numero_de_boleta_sin_titulo(self):
        self.assertEqual(detectar_boleta()["boleta.boleta_numero"]["valor"], "77123/2025")

    def test_periodos_de_la_tabla(self):
        c = detectar_boleta()["boleta.periodos"]
        self.assertEqual(c["valor"], ["2020-11", "2021-01", "2023-06"])  # sin 2031 ni el mes de emisión
        self.assertEqual(c["candidatos"][0]["regla"], "periodos-tabla-mes")
        self.assertLess(c["candidatos"][0]["confianza"], 0.85)  # OCR

    def test_el_mes_de_emision_no_es_periodo(self):
        txt = "N 77123/2025\na los 06 días del mes de NOVIEMBRE de 2025."
        self.assertFalse(detectar_boleta(txt)["boleta.periodos"]["candidatos"])

    def test_monto_intereses(self):
        c = detectar_boleta()
        self.assertEqual(c["boleta.monto_intereses"]["valor"], "500.50")
        self.assertEqual(c["boleta.monto_capital"]["valor"], "1000.00")


class TestChequeosNuevo(unittest.TestCase):
    def por_id(self, caso):
        return {c["id"]: c for c in chequeos.chequear(caso, CONFIG)}

    def test_a1_sin_expediente(self):
        r = self.por_id(caso_base(**{"demanda.expediente_numero": None}))["A1"]
        self.assertEqual(r["resultado"], "FALTA")
        self.assertIn("Cargá el número de expediente que asignó mesa de entradas: la demanda no lo trae.", r["detalle"])

    def test_b8_suma(self):
        extra = {"boleta.monto_capital": "1000.00", "boleta.monto_intereses": "200.50", "boleta.monto_total": "1200.50"}
        self.assertEqual(self.por_id(caso_base(**extra))["B8"]["resultado"], "OK")
        extra["boleta.monto_total"] = "1200.55"   # dentro de la tolerancia
        self.assertEqual(self.por_id(caso_base(**extra))["B8"]["resultado"], "OK")
        extra["boleta.monto_total"] = "1300.00"
        self.assertEqual(self.por_id(caso_base(**extra))["B8"]["resultado"], "OBSERVAR")
        self.assertNotIn("B8", self.por_id(caso_base()))  # sin intereses no hay chequeo

    def test_b3_digito_invalido_observa(self):
        r = self.por_id(caso_base(**{"boleta.ejecutado_documento": "27123456789"}))["B3"]
        self.assertEqual(r["resultado"], "OBSERVAR")
        self.assertIn("dígito verificador", r["detalle"])

    def test_solo_boleta_no_es_falta(self):
        caso = caso_base(**{"demanda.boleta_fecha": None, "demanda.periodos": None})
        r = self.por_id(caso)
        self.assertEqual(r["E1"]["resultado"], "OK", r["E1"]["detalle"])


class TestServidorNuevo(unittest.TestCase):
    def caso(self, **vacios):
        campos = {k: {"valor": v, "confirmado": True} for k, v in caso_base()["campos"].items()}
        for k, v in vacios.items():
            campos[k.replace("__", ".")] = {"valor": v, "confirmado": False}
        return {"campos": campos, "cotejo": [], "chequeos": []}

    def test_opcionales_vacios_no_son_pendientes(self):
        caso = self.caso(demanda__boleta_fecha=None, demanda__periodos=[], demanda__boleta_numero="",
                         demanda__monto_capital=None, demanda__concepto=None, boleta__monto_intereses=None)
        self.assertEqual(servidor.pendientes(caso), [])
        caso["campos"]["demanda.ejecutante"] = {"valor": None, "confirmado": False}
        self.assertEqual(servidor.pendientes(caso), ["demanda.ejecutante"])
        caso["campos"]["demanda.concepto"] = {"valor": "algo", "confirmado": False}
        self.assertIn("demanda.concepto", servidor.pendientes(caso))

    def test_solo_boleta_no_bloquea(self):
        caso = self.caso()
        caso["cotejo"] = [{"campo": "boleta_fecha", "resultado": "SOLO BOLETA"}]
        self.assertEqual(servidor.motivos_bloqueo(caso), [])
        caso["cotejo"].append({"campo": "x", "resultado": "FALTA"})
        self.assertEqual(len(servidor.motivos_bloqueo(caso)), 1)

    def test_interfaz(self):
        web = Path(servidor.__file__).parent / "web"
        js = (web / "app.js").read_text(encoding="utf-8")
        self.assertIn("N° de expediente (lo asigna mesa de entradas)", js)
        self.assertIn("SOLO-BOLETA", js)
        self.assertIn("p-SOLO-BOLETA", (web / "estilos.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
