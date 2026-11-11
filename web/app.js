"use strict";
/* Constructor de monitorias · interfaz. JavaScript puro, sin internet. */

const ETIQUETAS = {
  ejecutante: "Ejecutante", letrado_nombre: "Letrado", letrado_matricula: "Matrícula",
  ejecutado_nombre: "Ejecutado", ejecutado_documento: "Documento", ejecutado_domicilio: "Domicilio",
  concepto: "Concepto", periodos: "Períodos", boleta_numero: "Número de boleta",
  boleta_fecha: "Fecha de emisión", monto_capital: "Monto de capital", monto_total: "Monto total",
  expediente_numero: "Expediente", caratula: "Carátula", unidad: "Unidad judicial",
  centro: "Centro judicial", nro_sentencia: "N.º de sentencia", fecha_sentencia: "Fecha de sentencia",
};
const GRUPOS = [["demanda", "Demanda"], ["boleta", "Boleta"], ["juzgado", "Juzgado"]];
const PASOS = ["Detectar", "Construir", "Chequear", "Generar"];
const ALTA = 0.8;

const app = {
  vista: "uno", paso: 1, caso: null, campoSel: null, config: null, ocr: null,
  chequeo: null, vistaPrevia: null, generado: false, motivos: [], lote: [], temporizador: null,
};

/* ---------- utilidades ---------- */
const $ = (s, r = document) => r.querySelector(s);

function el(tag, attrs, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const h of hijos.flat()) {
    if (h === null || h === undefined || h === false) continue;
    e.append(h.nodeType ? h : document.createTextNode(String(h)));
  }
  return e;
}

async function api(ruta, opciones = {}) {
  const init = { method: opciones.metodo || "GET", headers: {} };
  if (opciones.cuerpo !== undefined) {
    init.body = JSON.stringify(opciones.cuerpo);
    init.headers["Content-Type"] = "application/json";
  }
  const r = await fetch(ruta, init);
  const tipo = r.headers.get("Content-Type") || "";
  if (opciones.blob && r.ok) return { blob: await r.blob(), r };
  const datos = tipo.includes("json") ? await r.json() : null;
  if (!r.ok) {
    const e = new Error((datos && datos.error) || "Falló el pedido (" + r.status + ").");
    e.estado = r.status;
    e.datos = datos || {};
    throw e;
  }
  return datos;
}

function mostrarError(texto, lista) {
  const c = $("#mensaje");
  c.replaceChildren(texto);
  if (lista && lista.length) c.append(el("ul", {}, lista.map((x) => el("li", {}, x))));
  c.hidden = false;
  c.scrollIntoView({ block: "nearest" });
}
function limpiarError() { $("#mensaje").hidden = true; }

function descargar(blob, nombre) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: nombre });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function archivoABase64(archivo) {
  return new Promise((ok, mal) => {
    const lector = new FileReader();
    lector.onload = () => ok({ nombre: archivo.name, base64: String(lector.result).split(",")[1] || "" });
    lector.onerror = () => mal(new Error("No se pudo leer " + archivo.name));
    lector.readAsDataURL(archivo);
  });
}

function pdfs(lista) {
  return [...lista].filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
}

function activarSoltar(zona, input, alSoltar) {
  const recibir = (lista) => {
    const p = pdfs(lista);
    if (!p.length) return mostrarError("Solo se aceptan archivos PDF.");
    alSoltar(p);
  };
  ["dragenter", "dragover"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.add("sobre"); }));
  ["dragleave", "drop"].forEach((ev) => zona.addEventListener(ev, (e) => { e.preventDefault(); zona.classList.remove("sobre"); }));
  zona.addEventListener("drop", (e) => recibir(e.dataTransfer.files));
  input.addEventListener("change", () => { recibir(input.files); input.value = ""; });
}

const textoValor = (v) => (v === null || v === undefined ? "" : Array.isArray(v) ? v.join(", ") : String(v));
const igual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const claseConf = (c) => (c >= ALTA ? "alta" : c >= 0.5 ? "media" : "baja");
const pct = (c) => Math.round((c || 0) * 100) + " %";

function candidatoElegido(campo) {
  const cs = campo.candidatos || [];
  return cs.find((c) => igual(c.valor, campo.valor)) || null;
}
function revisarOcr(clave, campo) {
  const c = candidatoElegido(campo);
  return clave.startsWith("boleta.") && !!c && c.origen === "ocr";
}

/* ---------- vistas ---------- */
function cambiarVista(v) {
  app.vista = v;
  document.querySelectorAll(".vista-btn").forEach((b) => b.classList.toggle("activa", b.dataset.vista === v));
  $("#vista-uno").hidden = v !== "uno";
  $("#vista-lote").hidden = v !== "lote";
  limpiarError();
  clearInterval(app.temporizador);
  if (v === "lote") {
    refrescarLote();
    app.temporizador = setInterval(refrescarLote, 2000);
  } else dibujarUno();
}

/* ---------- Un expediente ---------- */
function irAPaso(n) {
  if (n > 1 && !app.caso) return;
  app.paso = n;
  limpiarError();
  dibujarUno();
  if (n === 3) chequear();
  if (n === 4) prepararGenerar();
}

function dibujarUno() {
  const pasos = $("#pasos");
  pasos.replaceChildren(...PASOS.map((nombre, i) => el("li", { class: app.paso === i + 1 ? "activo" : "" },
    el("button", { onclick: () => irAPaso(i + 1), disabled: i > 0 && !app.caso },
      el("span", { class: "num" }, i + 1), nombre))));
  const cont = $("#paso");
  cont.replaceChildren();
  if (app.paso === 1) cont.append(...pasoDetectar());
  if (app.paso === 2) cont.append(pasoConstruir());
  if (app.paso === 3) cont.append(...pasoChequear());
  if (app.paso === 4) cont.append(...pasoGenerar());
}

/* Paso 1: detectar */
function pasoDetectar() {
  const zona = el("div", { class: "soltar", tabindex: "0" },
    el("p", {}, el("strong", {}, "Soltá acá los PDF de UN expediente.")),
    el("p", { class: "chico" }, "Demanda, boleta y poder, en uno o varios archivos. O ",
      el("label", { class: "enlace" }, "elegilos", el("input", { type: "file", accept: "application/pdf,.pdf", multiple: true, hidden: true, id: "archivos-uno" })), "."));
  const estado = el("div", { id: "estado-subida" });
  setTimeout(() => activarSoltar(zona, $("#archivos-uno"), subirUno), 0);
  const salida = [zona, estado];
  if (app.caso) salida.push(listaPaginas());
  return salida;
}

async function subirUno(archivos) {
  limpiarError();
  const estado = $("#estado-subida");
  estado.replaceChildren(el("p", {}, "Leyendo " + archivos.length + " archivo(s) y detectando campos…"), el("div", { class: "progreso" }, el("div")));
  try {
    const cuerpo = { archivos: await Promise.all(archivos.map(archivoABase64)) };
    app.caso = await api("/api/casos", { metodo: "POST", cuerpo });
    app.campoSel = null; app.chequeo = null; app.vistaPrevia = null; app.generado = false;
    dibujarUno();
  } catch (e) {
    estado.replaceChildren();
    mostrarError(e.message);
  }
}

function listaPaginas() {
  const c = app.caso;
  const cab = el("div", { class: "acciones" },
    el("h2", {}, c.paginas.length + " páginas · organismo: " + ((c.organismo && c.organismo.valor) || "no se pudo detectar")),
    el("button", { class: "primario", onclick: () => irAPaso(2) }, "Seguir a Construir"));
  const grilla = el("div", { class: "paginas" }, c.paginas.map((p) => {
    const ocr = p.origen === "ocr";
    return el("div", { class: "pagina" },
      p.imagen ? el("img", { src: "/api/casos/" + c.id + "/pagina/" + p.n, alt: "Página " + p.n, loading: "lazy" })
        : el("div", { class: "sin-img" }, "Sin imagen"),
      el("div", { class: "meta" },
        el("strong", {}, "Pág. " + p.n),
        el("span", { class: "pildora" }, p.tipo || "otro"),
        el("span", { class: "pildora " + (ocr ? "p-media" : "") },
          p.origen === "vacia" ? "vacía" : ocr ? "OCR" + (p.confianza_ocr != null ? " " + pct(p.confianza_ocr) : "") : "texto")));
  }));
  return el("div", {}, cab, grilla);
}

/* Paso 2: construir */
async function guardarCampos(cambios) {
  try {
    app.caso = await api("/api/casos/" + app.caso.id + "/campos", { metodo: "PUT", cuerpo: cambios });
    app.chequeo = null; app.vistaPrevia = null; app.generado = false;
    dibujarUno();
  } catch (e) { mostrarError(e.message); }
}

function pasoConstruir() {
  const campos = app.caso.campos;
  const claves = Object.keys(campos);
  const altos = claves.filter((k) => {
    const c = campos[k], cand = candidatoElegido(c);
    return !c.confirmado && c.valor !== null && c.valor !== "" && cand && cand.confianza >= ALTA && !revisarOcr(k, c);
  });
  const pendientes = claves.filter((k) => !campos[k].confirmado).length;
  const izq = el("div", {},
    el("div", { class: "acciones" },
      el("button", { class: "primario", disabled: !altos.length, onclick: () => {
        const cambios = {};
        altos.forEach((k) => { cambios[k] = { confirmado: true }; });
        guardarCampos(cambios);
      } }, "Confirmar los de confianza alta (" + altos.length + ")"),
      el("span", { class: "chico" }, "Quedan " + pendientes + " sin confirmar de " + claves.length + ".")),
    GRUPOS.map(([pref, titulo]) => {
      const ks = claves.filter((k) => k.startsWith(pref + "."));
      return ks.length ? el("div", {}, el("h3", {}, titulo), ks.map(filaCampo)) : null;
    }),
    el("div", { class: "acciones" }, el("button", { class: "primario", onclick: () => irAPaso(3) }, "Seguir a Chequear")));
  const der = el("div", { class: "derecha tarjeta", id: "panel-pagina" });
  const caja = el("div", { class: "dos" }, izq, der);
  dibujarPanelPagina(der);
  return caja;
}

function filaCampo(clave) {
  const campo = app.caso.campos[clave];
  const nombre = clave.split(".")[1];
  const cand = candidatoElegido(campo);
  const esLista = Array.isArray(campo.valor);
  const entrada = el("input", { type: "text", value: textoValor(campo.valor), "aria-label": ETIQUETAS[nombre] || nombre,
    onclick: (e) => e.stopPropagation(),
    onchange: (e) => {
      const t = e.target.value.trim();
      const v = esLista ? t.split(",").map((x) => x.trim()).filter(Boolean) : t;
      guardarCampos({ [clave]: { valor: v } });
    } });
  const opciones = (campo.candidatos || []).map((c, i) =>
    el("option", { value: String(i), selected: igual(c.valor, campo.valor) },
      textoValor(c.valor) + " · pág. " + c.pagina + " · " + (c.origen === "ocr" ? "OCR" : "texto") + " " + pct(c.confianza)));
  const menu = (campo.candidatos || []).length > 1 || (campo.candidatos || []).length === 1 && !cand
    ? el("select", { "aria-label": "Otros candidatos", onclick: (e) => e.stopPropagation(),
        onchange: (e) => guardarCampos({ [clave]: { valor: campo.candidatos[Number(e.target.value)].valor } }) },
        cand ? null : el("option", { value: "", selected: true }, "(valor propio)"),
        opciones)
    : null;
  const conf = cand
    ? el("span", { class: "pildora p-" + claseConf(cand.confianza), title: "Confianza" }, pct(cand.confianza))
    : el("span", { class: "pildora" }, campo.valor ? "manual" : "sin dato");
  const origen = cand ? el("span", { class: "chico" }, (cand.origen === "ocr" ? "OCR" : "texto") + " · pág. " + cand.pagina) : null;
  return el("div", { class: "campo" + (campo.confirmado ? " ok" : "") + (app.campoSel === clave ? " sel" : ""),
    onclick: () => { app.campoSel = clave; dibujarUno(); } },
    el("div", { class: "cab" },
      el("span", { class: "nombre" }, ETIQUETAS[nombre] || nombre),
      el("span", { class: "fila" }, revisarOcr(clave, campo) ? el("span", { class: "pildora p-revisar" }, "Revisar a mano (OCR)") : null, conf, origen)),
    el("div", { class: "fila" }, entrada, menu,
      el("button", { class: campo.confirmado ? "chica" : "chica primario", onclick: (e) => {
        e.stopPropagation();
        if (campo.confirmado) return guardarCampos({ [clave]: { confirmado: false } });
        const t = entrada.value.trim();
        guardarCampos({ [clave]: { valor: esLista ? t.split(",").map((x) => x.trim()).filter(Boolean) : t, confirmado: true } });
      } }, campo.confirmado ? "Confirmado ✓" : "Confirmar")));
}

function marcarCita(texto, cita) {
  const limpia = (cita || "").replace(/^[…\.\s]+|[…\.\s]+$/g, "");
  const caja = el("div", { class: "texto-pagina" });
  if (!limpia) { caja.textContent = texto; return caja; }
  let i = texto.indexOf(limpia), largo = limpia.length;
  if (i < 0) {
    const patron = limpia.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
    const m = new RegExp(patron, "i").exec(texto);
    if (m) { i = m.index; largo = m[0].length; }
  }
  if (i < 0) { caja.textContent = texto; return caja; }
  caja.append(texto.slice(0, i), el("mark", { id: "marca-cita" }, texto.slice(i, i + largo)), texto.slice(i + largo));
  return caja;
}

function dibujarPanelPagina(panel) {
  const clave = app.campoSel;
  if (!clave || !app.caso.campos[clave]) {
    panel.append(el("p", { class: "chico" }, "Tocá un campo para ver la página de donde salió el dato."));
    return;
  }
  const campo = app.caso.campos[clave];
  const cand = candidatoElegido(campo) || (campo.candidatos || [])[0];
  panel.append(el("h2", {}, ETIQUETAS[clave.split(".")[1]] || clave));
  if (!cand) {
    panel.append(el("p", {}, "No hay candidatos. Cargalo a mano y confirmalo."));
    return;
  }
  const pag = app.caso.paginas.find((p) => p.n === cand.pagina);
  panel.append(el("p", { class: "chico" }, "Página " + cand.pagina + " · " + (cand.origen === "ocr" ? "OCR" : "texto") + " · regla " + (cand.regla || "—")),
    el("div", { class: "cita" }, "«" + (cand.cita || "") + "»"));
  if (pag && pag.imagen) panel.append(el("img", { class: "pagina-grande", alt: "Página " + pag.n, src: "/api/casos/" + app.caso.id + "/pagina/" + pag.n }));
  if (pag && pag.texto) panel.append(el("h3", {}, "Texto de la página"), marcarCita(pag.texto, cand.cita));
  setTimeout(() => { const m = $("#marca-cita"); if (m) m.scrollIntoView({ block: "center" }); }, 0);
}

/* Paso 3: chequear */
async function chequear() {
  const cont = $("#paso");
  cont.replaceChildren(el("p", {}, "Chequeando…"), el("div", { class: "progreso" }, el("div")));
  try {
    app.chequeo = await api("/api/casos/" + app.caso.id + "/chequear", { metodo: "POST" });
    app.caso.cotejo = app.chequeo.cotejo; app.caso.chequeos = app.chequeo.chequeos;
    app.caso.honorarios = app.chequeo.honorarios; app.caso.estado = app.chequeo.estado;
    app.motivos = app.chequeo.motivos || [];
  } catch (e) { mostrarError(e.message); app.chequeo = null; }
  if (app.paso === 3) { cont.replaceChildren(...pasoChequear()); }
}

function pasoChequear() {
  if (!app.chequeo) {
    return [el("div", { class: "acciones" }, el("button", { class: "primario", onclick: chequear }, "Chequear"))];
  }
  const { cotejo, chequeos, honorarios } = app.chequeo;
  const t = el("table", { class: "tabla" },
    el("thead", {}, el("tr", {}, ["Campo", "Demanda", "Boleta", "Resultado", "Detalle"].map((h) => el("th", {}, h)))),
    el("tbody", {}, (cotejo || []).map((f) => el("tr", {},
      el("td", {}, ETIQUETAS[f.campo] || f.campo), el("td", {}, textoValor(f.demanda) || "—"), el("td", {}, textoValor(f.boleta) || "—"),
      el("td", {}, el("span", { class: "pildora p-" + (f.resultado === "FALTA" ? "FALTA-cotejo" : f.resultado) }, f.resultado)),
      el("td", { class: "chico" }, f.detalle || "")))));
  const lista = el("ul", { class: "chequeos" }, (chequeos || []).map((c) => el("li", {},
    el("span", { class: "pildora p-" + c.resultado }, c.resultado),
    el("div", {}, el("strong", {}, c.titulo || c.id), c.detalle ? el("div", { class: "chico" }, c.detalle) : null))));
  return [
    el("div", { class: "tarjeta" }, el("h2", {}, "Cotejo: demanda frente a boleta"), el("div", { class: "tabla-caja" }, t)),
    el("div", { class: "dos" },
      el("div", { class: "tarjeta" }, el("h2", {}, "Chequeos"), lista),
      el("div", { class: "tarjeta" }, el("h2", {}, "Honorarios"), tarjetaHonorarios(honorarios))),
    el("div", { class: "acciones" },
      el("button", { onclick: chequear }, "Volver a chequear"),
      el("button", { class: "primario", onclick: () => irAPaso(4) }, "Seguir a Generar")),
  ];
}

function tarjetaHonorarios(h) {
  if (!h || !Object.keys(h).length) return el("p", { class: "chico" }, "Sin cálculo.");
  if (h.error) return el("p", { class: "chico" }, h.error);
  const filas = [];
  const agregar = (obj, prefijo) => Object.entries(obj).forEach(([k, v]) => {
    const nombre = (prefijo + k).replace(/_/g, " ");
    if (v && typeof v === "object" && !Array.isArray(v)) agregar(v, nombre + " · ");
    else filas.push(el("dt", {}, nombre), el("dd", {}, textoValor(typeof v === "boolean" ? (v ? "sí" : "no") : v)));
  });
  agregar(h, "");
  return el("dl", { class: "datos" }, filas);
}

/* Paso 4: generar */
async function prepararGenerar() {
  const cont = $("#paso");
  cont.replaceChildren(el("p", {}, "Armando la vista previa…"));
  try {
    if (!app.chequeo) {
      app.chequeo = await api("/api/casos/" + app.caso.id + "/chequear", { metodo: "POST" });
      app.motivos = app.chequeo.motivos || [];
    }
    app.vistaPrevia = (await api("/api/casos/" + app.caso.id + "/vista")).parrafos;
  } catch (e) { app.vistaPrevia = null; mostrarError(e.message); }
  if (app.paso === 4) cont.replaceChildren(...pasoGenerar());
}

function pasoGenerar() {
  const salida = [];
  if (app.motivos.length) {
    salida.push(el("div", { class: "aviso error" }, "Todavía no se puede generar:", el("ul", {}, app.motivos.map((m) => el("li", {}, m)))));
  }
  salida.push(el("div", { class: "acciones" },
    el("button", { class: "primario", disabled: app.motivos.length > 0, onclick: generarUno }, "Generar sentencia"),
    app.generado ? el("button", { onclick: bajarUno }, "Descargar sentencia.docx") : null));
  if (app.vistaPrevia) {
    salida.push(el("div", { class: "vista-previa" }, app.vistaPrevia.map((p) => el("p", { class: p.estilo || "parrafo" }, p.texto))));
  }
  return salida;
}

async function generarUno() {
  limpiarError();
  try {
    await api("/api/casos/" + app.caso.id + "/generar", { metodo: "POST" });
    app.generado = true;
    app.caso = await api("/api/casos/" + app.caso.id);
    app.chequeo = null;
    await prepararGenerar();
    bajarUno();
  } catch (e) {
    app.motivos = e.datos.motivos || app.motivos;
    mostrarError(e.message, e.datos.motivos);
    dibujarUno();
  }
}
async function bajarUno() {
  try {
    const { blob } = await api("/api/casos/" + app.caso.id + "/sentencia", { blob: true });
    descargar(blob, "sentencia-" + app.caso.id + ".docx");
  } catch (e) { mostrarError(e.message); }
}

/* ---------- Lote ---------- */
async function subirLote(archivos) {
  limpiarError();
  $("#estado-lote").textContent = "Subiendo " + archivos.length + " archivo(s)…";
  try {
    const cuerpo = { archivos: await Promise.all(archivos.map(archivoABase64)) };
    await api("/api/lote", { metodo: "POST", cuerpo });
    $("#estado-lote").textContent = "";
    refrescarLote();
  } catch (e) { mostrarError(e.message); $("#estado-lote").textContent = ""; }
}

async function refrescarLote() {
  try {
    app.lote = (await api("/api/casos")).casos;
    dibujarLote();
  } catch (e) { /* el servidor puede estar ocupado: se reintenta solo */ }
}

function dibujarLote() {
  const cuerpo = $("#tabla-lote tbody");
  const procesando = app.lote.filter((c) => c.estado === "procesando").length;
  $("#estado-lote").textContent = procesando ? "Procesando " + procesando + " expediente(s)…" : (app.lote.length ? app.lote.length + " expediente(s)." : "");
  cuerpo.replaceChildren(...(app.lote.length ? app.lote.map((c) => {
    const k = c.cotejo || {};
    const hayCotejo = (k.COINCIDE || 0) + (k.DIFIERE || 0) + (k.FALTA || 0) > 0;
    return el("tr", {},
      el("td", {}, c.estado === "procesando" ? "(procesando…)" : c.caratula, c.error ? el("div", { class: "chico" }, c.error) : null),
      el("td", {}, c.organismo || "—"),
      el("td", {}, el("span", { class: "pildora " + (c.estado === "generado" || c.estado === "chequeado" ? "p-ok" : c.estado === "error" ? "p-mal" : c.estado === "observado" ? "p-media" : "") }, c.estado)),
      el("td", {}, c.estado === "procesando" ? "—" : c.confirmados + " de " + c.total),
      el("td", {}, hayCotejo ? [
        k.COINCIDE ? el("span", { class: "pildora p-COINCIDE" }, k.COINCIDE + " coinciden ") : null, " ",
        k.DIFIERE ? el("span", { class: "pildora p-DIFIERE" }, k.DIFIERE + " difieren") : null, " ",
        k.FALTA ? el("span", { class: "pildora p-FALTA-cotejo" }, k.FALTA + " faltan") : null] : "—"),
      el("td", {}, el("button", { class: "chica", disabled: c.estado === "procesando" || c.estado === "error", onclick: () => abrirCaso(c.id) }, "Abrir")));
  }) : [el("tr", {}, el("td", { colspan: "6", class: "chico" }, "Todavía no hay expedientes. Soltá los PDF arriba."))]));
}

async function abrirCaso(id) {
  try {
    app.caso = await api("/api/casos/" + id);
    app.campoSel = null; app.chequeo = null; app.vistaPrevia = null; app.motivos = [];
    app.generado = app.caso.estado === "generado";
    app.paso = 2;
    cambiarVista("uno");
  } catch (e) { mostrarError(e.message); }
}

async function generarLote() {
  limpiarError();
  const b = $("#btn-generar-lote");
  b.disabled = true;
  try {
    const { blob, r } = await api("/api/lote/generar", { metodo: "POST", blob: true });
    descargar(blob, "sentencias.zip");
    const om = Number(r.headers.get("X-Omitidas") || 0);
    $("#estado-lote").textContent = "Generadas: " + r.headers.get("X-Generadas") + (om ? ". Omitidas: " + om + " (el detalle está en OMITIDAS.txt)." : ".");
  } catch (e) {
    const om = e.datos && e.datos.omitidas;
    mostrarError(e.message, om ? Object.entries(om).map(([id, ms]) => id + ": " + ms.join(" ")) : null);
  } finally { b.disabled = false; refrescarLote(); }
}

/* ---------- Configuración y estado ---------- */
async function cargarEstado() {
  try {
    const e = await api("/api/estado");
    app.config = e.config; app.ocr = e.ocr;
    const aviso = $("#aviso-ocr");
    aviso.hidden = e.ocr.disponible;
    if (!e.ocr.disponible) aviso.textContent = "No hay OCR: las páginas escaneadas se cargan a mano." + (e.ocr.motivo ? " (" + e.ocr.motivo + ")" : "");
  } catch (e) { mostrarError("No se pudo hablar con el servidor local."); }
}

function abrirConfig() {
  const f = $("#form-config"), c = app.config || {}, h = c.honorarios || {};
  f.unidad_judicial.value = c.unidad_judicial || "";
  f.centro_judicial.value = c.centro_judicial || "";
  f.ciudad.value = c.ciudad || "";
  f.proximo_nro_sentencia.value = c.proximo_nro_sentencia || 1;
  f.pct_art14.value = h.pct_art14 ?? 16;
  f.multiplicador.value = h.multiplicador ?? 1.55;
  f.minimo_cat.value = h.minimo_cat ?? "";
  f.reduccion.checked = h.reduccion !== false;
  f.modo_honorarios.value = h.modo || "regular";
  f.tasa_interes.value = c.tasa_interes || "";
  f.cuenta_judicial.value = c.cuenta_judicial || "";
  f.martillero.value = c.martillero || "";
  f.presupuesto_pct.value = c.presupuesto_pct ?? "";
  $("#dlg-config").showModal();
}

async function guardarConfig(e) {
  e.preventDefault();
  const f = $("#form-config");
  try {
    app.config = await api("/api/config", { metodo: "PUT", cuerpo: {
      unidad_judicial: f.unidad_judicial.value, centro_judicial: f.centro_judicial.value, ciudad: f.ciudad.value,
      proximo_nro_sentencia: f.proximo_nro_sentencia.value,
      tasa_interes: f.tasa_interes.value, cuenta_judicial: f.cuenta_judicial.value,
      martillero: f.martillero.value, presupuesto_pct: f.presupuesto_pct.value,
      honorarios: { modo: f.modo_honorarios.value, pct_art14: f.pct_art14.value, multiplicador: f.multiplicador.value,
        minimo_cat: f.minimo_cat.value, reduccion: f.reduccion.checked } } });
    $("#dlg-config").close();
  } catch (err) { mostrarError(err.message); $("#dlg-config").close(); }
}

/* ---------- arranque ---------- */
document.querySelectorAll(".vista-btn").forEach((b) => b.addEventListener("click", () => cambiarVista(b.dataset.vista)));
$("#btn-config").addEventListener("click", abrirConfig);
$("#guardar-config").addEventListener("click", guardarConfig);
$("#btn-generar-lote").addEventListener("click", generarLote);
activarSoltar($("#soltar-lote"), $("#archivos-lote"), subirLote);
cargarEstado();
dibujarUno();
