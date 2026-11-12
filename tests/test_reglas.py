"""Pruebas sinteticas de la logica de reglas. Complementan, no reemplazan, a C1/C2."""

from p6 import reglas


def ev(status="ok", zona=None):
    return {"status": status, "zona_frame": zona}


def ventana(*eventos):
    v = reglas.Ventana("v", "r", 1)
    v.eventos = list(eventos)
    return v


def test_conteos_separan_error_y_sin_detecciones():
    c = ventana(ev(zona="baja"), ev(zona="duda"), ev(), ev("error"), ev(zona="aceptada")).conteos()
    assert c == {
        "intentos": 5,
        "errores": 1,
        "sin_detecciones": 1,
        "puntuados": 3,
        "aceptada": 1,
        "duda": 1,
        "baja": 1,
    }


def test_ventana_insuficiente_no_es_normalidad():
    c = ventana(ev(zona="baja"), ev(), ev(), ev(), ev(), ev()).conteos()
    assert reglas.p_baja(c, 4) is None
    assert reglas.evaluar_baja(None, 0.5) == reglas.INSUFICIENTE


def test_regla_baja_confianza():
    c = ventana(ev(zona="baja"), ev(zona="baja"), ev(zona="duda"), ev(zona="aceptada")).conteos()
    p = reglas.p_baja(c, 4)
    assert p == 0.5
    assert reglas.evaluar_baja(p, 0.5) == reglas.CUMPLE
    assert reglas.evaluar_baja(0.49, 0.5) == reglas.NO_CUMPLE


def test_regla_errores():
    c = ventana(ev("error"), ev("error"), ev(zona="baja")).conteos()
    assert reglas.evaluar_errores(c, 0.5, 3) == reglas.CUMPLE
    assert reglas.evaluar_errores(ventana(ev("error")).conteos(), 0.5, 3) == reglas.INSUFICIENTE


def test_sostenida_requiere_k_ventanas_y_la_insuficiente_no_reinicia():
    s = reglas.Sostenida(p_referencia=0.2, tolerancia=0.3, consecutivas=3)
    assert s.evaluar("v1", 0.9) == reglas.NO_CUMPLE
    assert s.evaluar("v2", None) == reglas.INSUFICIENTE  # ni suma ni reinicia
    assert s.evaluar("v3", 0.6) == reglas.NO_CUMPLE
    assert s.evaluar("v4", 0.51) == reglas.CUMPLE
    assert s.ventanas_racha() == ["v1", "v3", "v4"]
    assert s.evaluar("v5", 0.5) == reglas.NO_CUMPLE  # 0.5 no supera 0.2 + 0.3
    assert s.ventanas_racha() == []


def test_sostenida_sin_referencia_queda_inactiva():
    assert reglas.Sostenida(None, 0.3, 3).evaluar("v1", 1.0) == reglas.INACTIVA
