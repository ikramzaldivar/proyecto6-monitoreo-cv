"""Ventanas y reglas de alerta (logica pura, sin E/S; la usa `p6.monitor`).

Ventana: bloque consecutivo, sin traslape, de `tamano_ventana` frames procesados de una
corrida (intentos: ok y error). Una ventana parcial al final de la corrida tambien se
evalua. Conteos por ventana:

- intentos: frames procesados; errores: status=error;
- sin_detecciones: status=ok sin candidatas (no tienen puntuacion);
- puntuados: status=ok con al menos una candidata; se reparten en aceptada/duda/baja;
- p_baja = baja / puntuados, solo si puntuados >= minimo_puntuados. Si no, la ventana es
  `insuficiente` y p_baja queda en null: evidencia insuficiente, no normalidad.

Reglas (parametros en config/monitoreo.yaml):

- baja-confianza: ventana suficiente con p_baja >= proporcion_minima.
- cambio-sostenido: p_baja > p_baja_referencia + tolerancia en `ventanas_consecutivas`
  ventanas suficientes seguidas. Una ventana insuficiente no suma ni reinicia la racha;
  una ventana suficiente que no cumple la reinicia. Sin referencia la regla queda inactiva.
- errores-inferencia: intentos >= minimo_intentos y errores/intentos >= proporcion_minima.
- fuente-detenida: la evalua el monitor por tiempo (sin frames nuevos por mas del limite).

Ciclo de una alerta: se abre la primera vez que su regla se cumple; mientras siga
cumpliendose acumula ventanas y eventos; se resuelve en la primera ventana evaluable que
no la cumple. Una ventana no evaluable (insuficiente) no la resuelve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from p6.politica import ACEPTADA, BAJA, DUDA

CUMPLE, NO_CUMPLE, INSUFICIENTE, INACTIVA = "cumple", "no_cumple", "insuficiente", "inactiva"


@dataclass
class Ventana:
    ventana_id: str
    run_id: str
    indice: int
    eventos: list[dict[str, Any]] = field(default_factory=list)

    def conteos(self) -> dict[str, int]:
        c = {"intentos": 0, "errores": 0, "sin_detecciones": 0, "puntuados": 0}
        c |= {ACEPTADA: 0, DUDA: 0, BAJA: 0}
        for e in self.eventos:
            c["intentos"] += 1
            if e["status"] == "error":
                c["errores"] += 1
            elif e["zona_frame"] is None:
                c["sin_detecciones"] += 1
            else:
                c["puntuados"] += 1
                c[e["zona_frame"]] += 1
        return c


def p_baja(conteos: dict[str, int], minimo_puntuados: int) -> float | None:
    if conteos["puntuados"] < minimo_puntuados or conteos["puntuados"] == 0:
        return None
    return conteos[BAJA] / conteos["puntuados"]


def evaluar_baja(p: float | None, proporcion_minima: float) -> str:
    if p is None:
        return INSUFICIENTE
    return CUMPLE if p >= proporcion_minima else NO_CUMPLE


def evaluar_errores(conteos: dict[str, int], proporcion_minima: float, minimo: float) -> str:
    if conteos["intentos"] < minimo or conteos["intentos"] == 0:
        return INSUFICIENTE
    return CUMPLE if conteos["errores"] / conteos["intentos"] >= proporcion_minima else NO_CUMPLE


@dataclass
class Sostenida:
    """Racha de ventanas suficientes por encima de referencia + tolerancia."""

    p_referencia: float | None
    tolerancia: float
    consecutivas: int
    racha: list[str] = field(default_factory=list)

    @property
    def limite(self) -> float | None:
        return None if self.p_referencia is None else self.p_referencia + self.tolerancia

    def evaluar(self, ventana_id: str, p: float | None) -> str:
        if self.p_referencia is None:
            return INACTIVA
        if p is None:
            return INSUFICIENTE  # ni suma ni reinicia
        if p > self.limite:
            self.racha.append(ventana_id)
            return CUMPLE if len(self.racha) >= self.consecutivas else NO_CUMPLE
        self.racha.clear()
        return NO_CUMPLE

    def ventanas_racha(self) -> list[str]:
        return list(self.racha)
