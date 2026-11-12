"""Politica de confianza: dos umbrales y tres zonas.

`inferior <= s < superior` es duda; `s < inferior` es baja; `s >= superior` es aceptada por
politica (no afirma que la prediccion sea correcta). Un frame sin detecciones o con fallo
no tiene puntuacion ni zona: son estados aparte y no entran en el denominador de p_baja.

Unidad de analisis: el frame. Su puntuacion es la maxima entre sus detecciones candidatas
(las que superan el piso de salida del detector tras el NMS). Cada deteccion conserva
ademas su propia zona.
"""

from __future__ import annotations

ACEPTADA, DUDA, BAJA = "aceptada", "duda", "baja"


def zona(score: float | None, inferior: float, superior: float) -> str | None:
    if score is None:
        return None
    if not 0 <= inferior < superior <= 1:
        raise ValueError("se requiere 0 <= inferior < superior <= 1")
    if score >= superior:
        return ACEPTADA
    if score >= inferior:
        return DUDA
    return BAJA


def score_frame(scores: list[float]) -> float | None:
    """Puntuacion del frame: la maxima de sus candidatas, o None si no hay ninguna."""
    return max(scores) if scores else None
