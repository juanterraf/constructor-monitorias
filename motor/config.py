# Traduce la configuración del juzgado (config.local.json, la que guarda el servidor) al formato plano
# que usan chequeos y redacción. Una sola fuente: si cambia un nombre, se cambia acá.
def para_motor(cfg):
    cfg = dict(cfg or {})
    h = cfg.get("honorarios")
    if isinstance(h, dict):
        modo = h.get("modo") or "regular"
    else:  # ya viene plano ("regular" o "diferir")
        modo, h = (str(h) if h else "regular"), {}
    plano = dict(cfg)
    plano.update({
        "honorarios": modo,
        "pct_art14": h.get("pct_art14", cfg.get("pct_art14", 16)),
        "multiplicador": h.get("multiplicador", cfg.get("multiplicador", 1.55)),
        "reduccion": h.get("reduccion", cfg.get("reduccion", True)),
        "minimo_cat": h.get("minimo_cat", cfg.get("minimo_cat")),
        "lugar": cfg.get("lugar") or cfg.get("ciudad"),
        "unidad": cfg.get("unidad") or cfg.get("unidad_judicial"),
        "centro": cfg.get("centro") or cfg.get("centro_judicial"),
    })
    return plano
