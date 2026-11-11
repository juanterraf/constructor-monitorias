"""Pruebas de las reglas y la redacción. Datos inventados. Correr: python -m unittest tests.test_reglas -v"""
import re
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor import chequeos, cotejo, honorarios, letras, redactar  # noqa: E402


def campo(valor, confirmado=True):
    return {"valor": valor, "confirmado": confirmado, "candidatos": []}


def caso_base(organismo="SAT", **cambios):
    """Caso inventado, completo y coherente."""
    c = {
        "demanda.ejecutante": "Sociedad Aguas del Tucumán S.A.P.E.M.",
        "demanda.letrado_nombre": "Lucía Ferreyra",
        "demanda.letrado_matricula": "T° 99 F° 123",
        "demanda.ejecutado_nombre": "PEREZ JUAN",
        "demanda.ejecutado_documento": "20-11111111-2",
        "demanda.ejecutado_domicilio": "Calle Falsa 123, San Miguel de Tucumán",
        "demanda.concepto": "servicio de agua potable",
        "demanda.periodos": ["2025-01", "2025-02", "2025-03"],
        "demanda.boleta_numero": "1000/2025",
        "demanda.boleta_fecha": "2025-06-10",
        "demanda.monto_capital": "1000.00",
        "demanda.monto_total": "1200.50",
        "demanda.expediente_numero": "1234/25",
        "demanda.caratula": "SOCIEDAD AGUAS DEL TUCUMAN S.A.P.E.M. c/ PEREZ JUAN s/ COBRO EJECUTIVO",
        "demanda.fecha": "2025-07-01",
        "boleta.ejecutante": "SOCIEDAD AGUAS DEL TUCUMAN S.A.P.E.M.",
        "boleta.ejecutado_nombre": "Juan Pérez",
        "boleta.ejecutado_documento": "20111111112",
        "boleta.ejecutado_domicilio": "CALLE FALSA 123 - SAN MIGUEL DE TUCUMAN",
        "boleta.concepto": "servicio de agua potable",
        "boleta.periodos": ["2025-03", "2025-01", "2025-02"],
        "boleta.boleta_numero": "1000/2025",
        "boleta.boleta_fecha": "2025-06-10",
        "boleta.monto_capital": "1000.00",
        "boleta.monto_total": "1200.50",
        "juzgado.unidad": "OFICINA DE GESTIÓN ASOCIADA EN COBROS Y APREMIOS N° 1",
        "juzgado.centro": "Capital",
        "juzgado.nro_sentencia": "100",
        "juzgado.fecha_sentencia": "2025-08-15",
    }
    c.update(cambios)
    campos = {k: campo(v) for k, v in c.items() if v is not None}
    return {"id": "c-test", "organismo": {"valor": organismo}, "campos": campos, "cotejo": [], "chequeos": [], "honorarios": {}}


# La mayoría de los tests prueba el modo «diferir»; el modo «regular» (el defecto del juzgado) tiene su propio test.
CONFIG = {"honorarios": "diferir", "hoy": "2025-09-01", "ahora": "2025-09-01T10:30:00", "tasa_interes": "tasa activa promedio del BNRA",
          "presupuesto_pct": 30, "martillero": "el martillero público [COMPLETAR: nombre]"}


class TestCotejo(unittest.TestCase):
    def filas(self, **cambios):
        caso = caso_base(**cambios)
        return {f["campo"]: f for f in cotejo.cotejar(caso["campos"])}

    def test_coincide_con_nombres_en_otro_orden_y_periodos_desordenados(self):
        f = self.filas()
        for nombre, fila in f.items():
            self.assertEqual(fila["resultado"], "COINCIDE", f"{nombre}: {fila['detalle']}")

    def test_monto_distinto_informa_diferencia(self):
        f = self.filas(**{"boleta.monto_total": "1300.00"})
        self.assertEqual(f["monto_total"]["resultado"], "DIFIERE")
        self.assertIn("99.50", f["monto_total"]["detalle"])

    def test_cuit_distinto(self):
        f = self.filas(**{"boleta.ejecutado_documento": "20-11111112-0"})
        self.assertEqual(f["ejecutado_documento"]["resultado"], "DIFIERE")

    def test_periodos_otro_orden_coinciden_y_faltante_difiere(self):
        self.assertEqual(self.filas(**{"boleta.periodos": ["2025-02", "2025-03", "2025-01"]})["periodos"]["resultado"], "COINCIDE")
        f = self.filas(**{"boleta.periodos": ["2025-01", "2025-02"]})["periodos"]
        self.assertEqual(f["resultado"], "DIFIERE")
        self.assertIn("2025-03", f["detalle"])

    def test_falta(self):
        f = self.filas(**{"boleta.concepto": None})
        self.assertEqual(f["concepto"]["resultado"], "FALTA")
        self.assertIn("boleta", f["concepto"]["detalle"])

    def test_nombres_y_domicilio(self):
        self.assertEqual(cotejo._cmp_nombre("PEREZ JUAN", "Juan Pérez")[0], "COINCIDE")
        self.assertEqual(cotejo._cmp_nombre("PEREZ JUAN", "Juan Carlos Pérez")[0], "DIFIERE")
        self.assertEqual(cotejo._cmp_domicilio("Calle Falsa N° 123", "FALSA 123 calle")[0], "COINCIDE")
        self.assertEqual(cotejo._cmp_domicilio("Calle Falsa 123", "Calle Falsa 321")[0], "DIFIERE")


class TestChequeos(unittest.TestCase):
    def por_id(self, caso, config=CONFIG):
        return {c["id"]: c for c in chequeos.chequear(caso, config)}

    def test_caso_completo(self):
        r = self.por_id(caso_base())
        for id_ in ("A1", "A2", "A3", "B1", "B2", "B3", "B4", "B5", "C1", "C2", "D1", "E1", "F1", "G1", "H1"):
            self.assertEqual(r[id_]["resultado"], "OK", f"{id_}: {r[id_]['detalle']}")
        self.assertEqual(r["B6"]["resultado"], "MANUAL")
        self.assertEqual(r["B7"]["resultado"], "MANUAL")
        for c in r.values():
            self.assertEqual(set(c), {"id", "titulo", "resultado", "detalle"})

    def test_cuit(self):
        self.assertTrue(chequeos.cuit_valido("20-11111111-2"))
        self.assertFalse(chequeos.cuit_valido("20-11111111-3"))
        self.assertEqual(self.por_id(caso_base(**{"demanda.ejecutado_documento": "20-11111111-3", "boleta.ejecutado_documento": None}))["B3"]["resultado"], "OBSERVAR")
        self.assertEqual(self.por_id(caso_base(**{"demanda.ejecutado_documento": "27333444", "boleta.ejecutado_documento": "27333444"}))["B3"]["resultado"], "OK")

    def test_total_menor_que_capital(self):
        self.assertEqual(self.por_id(caso_base(**{"demanda.monto_total": "900.00", "boleta.monto_total": "900.00"}))["B4"]["resultado"], "OBSERVAR")

    def test_periodo_futuro_y_emision_posterior(self):
        self.assertEqual(self.por_id(caso_base(**{"boleta.periodos": ["2025-01", "2026-01"]}))["B5"]["resultado"], "OBSERVAR")
        self.assertEqual(self.por_id(caso_base(**{"boleta.boleta_fecha": "2025-08-01", "demanda.boleta_fecha": "2025-08-01", "demanda.fecha": "2025-07-01"}))["B2"]["resultado"], "OBSERVAR")

    def test_titulo_sin_numero_falta(self):
        r = self.por_id(caso_base(**{"boleta.boleta_numero": None}))
        self.assertEqual(r["B1"]["resultado"], "FALTA")

    def test_via_y_ejecutante(self):
        self.assertEqual(self.por_id(caso_base(organismo=None))["C1"]["resultado"], "FALTA")
        r = self.por_id(caso_base(organismo="DGR"))
        self.assertEqual(r["C1"]["resultado"], "OK")
        self.assertEqual(r["C2"]["resultado"], "OBSERVAR")  # ejecutante de SAT con organismo DGR: residuo de plantilla

    def test_letrado_sin_matricula(self):
        self.assertEqual(self.por_id(caso_base(**{"demanda.letrado_matricula": None}))["D1"]["resultado"], "FALTA")

    def test_sede_por_domicilio(self):
        self.assertEqual(chequeos.centro_notificacion("Av. X 100, Concepción, Tucumán"), "Concepción")
        self.assertEqual(chequeos.centro_notificacion("Calle 1, S.M. de Tucumán"), "Capital")
        self.assertIsNone(chequeos.centro_notificacion("Ruta 9 km 5"))
        r = self.por_id(caso_base(**{"demanda.ejecutado_domicilio": "Calle 1 - CONCEPCION", "boleta.ejecutado_domicilio": "Calle 1 - CONCEPCION"}))
        self.assertIn("Concepción", r["A2"]["detalle"])
        self.assertEqual(self.por_id(caso_base(**{"demanda.ejecutado_domicilio": "Ruta 9", "boleta.ejecutado_domicilio": "Ruta 9"}))["A2"]["resultado"], "MANUAL")

    def test_criterio_va_manual_y_sin_confirmar_falta(self):
        r = self.por_id(caso_base(), {"hoy": "2025-09-01"})
        self.assertEqual(r["F1"]["resultado"], "MANUAL")
        caso = caso_base()
        caso["campos"]["demanda.concepto"]["confirmado"] = False
        self.assertEqual(self.por_id(caso)["H1"]["resultado"], "FALTA")


class TestHonorarios(unittest.TestCase):
    """Casos portados de src/lib/honorarios/calc.test.ts."""

    def test_parse_monto(self):
        self.assertEqual(honorarios.parse_monto("458.320,50"), Decimal("458320.50"))
        self.assertEqual(honorarios.parse_monto("$ 1.000.000"), Decimal(1000000))
        self.assertEqual(honorarios.parse_monto(""), Decimal(0))
        self.assertEqual(honorarios.parse_monto("12345.67"), Decimal("12345.67"))

    def test_formula(self):
        r = honorarios.calcular(1000000, reduccion=True, pct_art14=16, multiplicador=1.55)
        self.assertEqual(r["calculado"], Decimal("124000.00"))
        self.assertEqual(r["final"], Decimal("124000.00"))

    def test_minimo_cat(self):
        r = honorarios.calcular(100000, minimo_cat=50000)
        self.assertTrue(r["aplica_minimo"])
        self.assertEqual(r["final"], Decimal("50000.00"))

    def test_sin_reduccion_duplica(self):
        con = honorarios.calcular(1000000, reduccion=True)
        sin = honorarios.calcular(1000000, reduccion=False)
        self.assertEqual(sin["calculado"], con["calculado"] * 2)

    def test_formato(self):
        self.assertEqual(honorarios.fmt_ars(Decimal("88117.51")), "$88.117,51")


class TestLetras(unittest.TestCase):
    def test_casos(self):
        L = letras.monto_en_letras
        self.assertEqual(L(Decimal("1234567.89")), "un millón doscientos treinta y cuatro mil quinientos sesenta y siete pesos con ochenta y nueve centavos")
        self.assertEqual(L(Decimal("88117.51")), "ochenta y ocho mil ciento diecisiete pesos con cincuenta y un centavos")
        self.assertEqual(L(Decimal("1")), "un peso con cero centavos")
        self.assertEqual(L(Decimal("21.01")), "veintiún pesos con un centavo")
        self.assertEqual(L(Decimal("2000000")), "dos millones de pesos con cero centavos")
        self.assertEqual(L(Decimal("1000.00")), "mil pesos con cero centavos")
        self.assertEqual(L(Decimal("100")), "cien pesos con cero centavos")


class TestRedaccion(unittest.TestCase):
    def test_cuerpo_por_organismo(self):
        for org, ejecutante in (("SAT", None), ("DGR", "DIRECCIÓN GENERAL DE RENTAS"), ("MUNICIPALIDAD", "MUNICIPALIDAD DE LA CIUDAD")):
            cambios = {"demanda.ejecutante": ejecutante, "boleta.ejecutante": ejecutante} if ejecutante else {}
            caso = caso_base(organismo=org, **cambios)
            cuerpo = redactar.armar_cuerpo(caso, CONFIG)
            texto = "\n".join(p["texto"] for p in cuerpo)
            estilos = {p["estilo"] for p in cuerpo}
            self.assertEqual(estilos, {"titulo", "parrafo", "resuelvo"})
            for ref in ("AUTOS Y VISTOS", "CONSIDERANDO", "RESUELVO", "MIL DOSCIENTOS PESOS CON CINCUENTA CENTAVOS", "$1.200,50",
                        "CUIT/CUIL N° 20-11111111-2", "tasa activa promedio del BNRA", "Centro Judicial Capital", "DIFERIR HONORARIOS"):
                self.assertIn(ref, texto, f"{org}: falta {ref}")
            self.assertNotIn("{", texto)
            self.assertIn("Ley N° 5.529" if org == "MUNICIPALIDAD" else "Ley 6529" if org == "SAT" else "Ley N° 5.121", texto)

    def test_completar_cuando_falta_criterio(self):
        caso = caso_base(**{"demanda.fecha": None})
        texto = "\n".join(p["texto"] for p in redactar.armar_cuerpo(caso, {"hoy": "2025-09-01"}))
        self.assertIn("[COMPLETAR: fecha de presentación de la demanda]", texto)
        self.assertIn("[COMPLETAR: tasa de interés]", texto)
        self.assertIn("[COMPLETAR: monto presupuestado", texto)
        self.assertGreaterEqual(len(redactar.pendientes(redactar.armar_cuerpo(caso, {}))), 4)

    def test_honorarios_regulados(self):
        caso = caso_base()
        texto = "\n".join(p["texto"] for p in redactar.armar_cuerpo(caso, dict(CONFIG, honorarios="regular", minimo_cat="50")))
        self.assertIn("REGULAR HONORARIOS", texto)
        self.assertNotIn("DIFERIR HONORARIOS", texto)
        self.assertIn("$148,86", texto)  # 1200,50 x 0,5 x 0,16 x 1,55; el mínimo de 50 no aplica

    def test_numeracion_romana_del_resuelvo(self):
        cuerpo = redactar.armar_cuerpo(caso_base(), CONFIG)
        res = [p["texto"] for p in cuerpo if p["estilo"] == "resuelvo"]
        self.assertTrue(res[0].startswith("I. ") and res[1].startswith("II. ") and res[3].startswith("IV. "))

    def test_docx(self):
        import docx
        caso = caso_base()
        with tempfile.TemporaryDirectory() as d:
            ruta = redactar.generar_docx(caso, CONFIG, Path(d) / "sentencia.docx")
            doc = docx.Document(ruta)
            texto = "\n".join(p.text for p in doc.paragraphs)
            for t in doc.tables:
                for fila in t.rows:
                    for celda in fila.cells:
                        texto += "\n" + celda.text
            self.assertIsNone(re.search(r"\{[@A-Za-z_]+\}", texto), "quedaron marcadores sin reemplazar")
            self.assertIn("SENTENCIA EJECUTIVA MONITORIA", texto)
            self.assertIn("EXPTE. N° 1234/25", texto)
            self.assertIn("01/09/2025 - 10:30:00", texto)
            self.assertIn("NRO. SENT.: 100", texto)
            self.assertIn("15/08/2025", texto)
            self.assertIn("CENTRO JUDICIAL CAPITAL", texto)
            negritas = [r.text for p in doc.paragraphs for r in p.runs if r.bold]
            self.assertIn("RESUELVO", negritas)
            with zipfile.ZipFile(ruta) as z:
                self.assertIsNone(z.testzip())

    def test_docx_con_marcador_partido_en_runs_y_xml_escapado(self):
        import docx
        caso = caso_base(**{"demanda.caratula": "A & B <S.A.> c/ PEREZ s/ COBRO"})
        base = redactar.PLANTILLA_DOCX
        with tempfile.TemporaryDirectory() as d:
            partida = Path(d) / "partida.docx"
            with zipfile.ZipFile(base) as zin, zipfile.ZipFile(partida, "w") as zout:
                for it in zin.infolist():
                    datos = zin.read(it.filename)
                    if it.filename == "word/document.xml":
                        x = datos.decode("utf-8")
                        x = x.replace('{expediente}</w:t></w:r>', '{expe</w:t></w:r><w:r><w:t xml:space="preserve">diente}</w:t></w:r>', 1)
                        datos = x.encode("utf-8")
                    zout.writestr(it, datos)
            anterior = redactar.PLANTILLA_DOCX
            redactar.PLANTILLA_DOCX = partida
            try:
                ruta = redactar.generar_docx(caso, CONFIG, Path(d) / "s.docx")
            finally:
                redactar.PLANTILLA_DOCX = anterior
            texto = "\n".join(p.text for p in docx.Document(ruta).paragraphs)
            self.assertIn("Expediente: 1234/25", texto)
            self.assertIn("A & B <S.A.> c/ PEREZ s/ COBRO", texto)
            self.assertIsNone(re.search(r"\{[@A-Za-z_]+\}", texto))


if __name__ == "__main__":
    unittest.main()
