"""Carga y valida `config/monitoreo.yaml`.

Rechaza claves desconocidas, umbrales fuera de `0 <= inferior < superior <= 1` y ventanas
sin sentido. Devuelve un `Config` inmutable con el SHA-256 del archivo, que se usa como
`config_ref` en eventos, ventanas y alertas para reconstruir la configuracion usada.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """La configuracion no se puede usar."""


@dataclass(frozen=True)
class Regla:
    rule_id: str
    severidad: str
    accion: str
    parametros: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    ruta: Path
    sha256: str
    config_id: str
    source_id: str
    fps: float
    cola_max: int
    limite_sin_frames_s: float
    detector: Path
    umbral_inferior: float
    umbral_superior: float
    tamano_ventana: int
    minimo_puntuados: int
    referencia: Path
    reglas: dict[str, Regla]
    captura_zonas: tuple[str, ...]
    captura_errores: bool
    captura_alertas: bool
    muestra_normal_cada: int
    crudo: dict[str, Any]

    @property
    def config_ref(self) -> str:
        return f"{self.config_id}@{self.sha256[:12]}"


ESTRUCTURA = {
    "version": None,
    "config_id": None,
    "fuente": {"source_id", "fps", "cola_max", "limite_sin_frames_s"},
    "detector": None,
    "politica": {"umbral_inferior", "umbral_superior"},
    "ventanas": {"tamano_frames", "minimo_puntuados"},
    "referencia": None,
    "reglas": {"baja_confianza", "cambio_sostenido", "errores_inferencia", "fuente_detenida"},
    "captura": {"zonas", "errores", "alertas", "muestra_normal_cada"},
}
PARAMETROS_REGLA = {
    "baja_confianza": {"proporcion_minima"},
    "cambio_sostenido": {"tolerancia", "ventanas_consecutivas"},
    "errores_inferencia": {"proporcion_minima", "minimo_intentos"},
    "fuente_detenida": set(),
}
ZONAS = ("aceptada", "duda", "baja")


def sha256_bytes(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _num(valor: Any) -> bool:
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def cargar(ruta: str | Path) -> Config:
    ruta = Path(ruta).resolve()
    try:
        bruto = ruta.read_bytes()
        data = yaml.safe_load(bruto)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"{ruta}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{ruta}: se esperaba un mapa")
    errores: list[str] = []
    if extra := set(data) - set(ESTRUCTURA):
        errores.append(f"claves desconocidas {sorted(extra)}")
    for clave, hijos in ESTRUCTURA.items():
        if clave not in data:
            errores.append(f"falta {clave}")
        elif hijos is not None:
            if not isinstance(data[clave], dict):
                errores.append(f"{clave} debe ser un mapa")
            elif extra := set(data[clave]) ^ hijos:
                errores.append(f"{clave}: claves faltantes o desconocidas {sorted(extra)}")
    if errores:
        raise ConfigError(f"{ruta}: " + "; ".join(errores))
    if data["version"] != 1:
        errores.append("version debe ser 1")

    fuente, pol, ven, cap = data["fuente"], data["politica"], data["ventanas"], data["captura"]
    inf, sup = pol["umbral_inferior"], pol["umbral_superior"]
    if not (_num(inf) and _num(sup) and 0 <= inf < sup <= 1):
        errores.append("politica: se requiere 0 <= umbral_inferior < umbral_superior <= 1")
    if not (_num(fuente["fps"]) and fuente["fps"] > 0):
        errores.append("fuente.fps debe ser positivo")
    if not (isinstance(fuente["cola_max"], int) and fuente["cola_max"] > 0):
        errores.append("fuente.cola_max debe ser entero positivo")
    if not (_num(fuente["limite_sin_frames_s"]) and fuente["limite_sin_frames_s"] > 0):
        errores.append("fuente.limite_sin_frames_s debe ser positivo")
    tam, minimo = ven["tamano_frames"], ven["minimo_puntuados"]
    if not (isinstance(tam, int) and isinstance(minimo, int) and 1 <= minimo <= tam):
        errores.append("ventanas: se requiere 1 <= minimo_puntuados <= tamano_frames (enteros)")
    if not set(cap["zonas"]) <= set(ZONAS):
        errores.append(f"captura.zonas debe estar en {ZONAS}")
    if not (isinstance(cap["muestra_normal_cada"], int) and cap["muestra_normal_cada"] >= 1):
        errores.append("captura.muestra_normal_cada debe ser entero >= 1")

    reglas: dict[str, Regla] = {}
    for nombre, esperados in PARAMETROS_REGLA.items():
        r = data["reglas"].get(nombre)
        if not isinstance(r, dict):
            errores.append(f"reglas.{nombre} debe ser un mapa")
            continue
        base = {"rule_id", "severidad", "accion"}
        if extra := set(r) ^ (base | esperados):
            errores.append(f"reglas.{nombre}: claves faltantes o desconocidas {sorted(extra)}")
            continue
        params = {k: r[k] for k in esperados}
        if not all(_num(v) and v >= 0 for v in params.values()):
            errores.append(f"reglas.{nombre}: parametros numericos no negativos")
        for k in ("proporcion_minima", "tolerancia"):
            if k in params and _num(params[k]) and not 0 <= params[k] <= 1:
                errores.append(f"reglas.{nombre}.{k} debe estar en [0, 1]")
        reglas[nombre] = Regla(str(r["rule_id"]), str(r["severidad"]), str(r["accion"]), params)
    if errores:
        raise ConfigError(f"{ruta}: " + "; ".join(errores))

    base = ruta.parent
    return Config(
        ruta=ruta,
        sha256=sha256_bytes(bruto),
        config_id=str(data["config_id"]),
        source_id=str(fuente["source_id"]),
        fps=float(fuente["fps"]),
        cola_max=fuente["cola_max"],
        limite_sin_frames_s=float(fuente["limite_sin_frames_s"]),
        detector=(base / data["detector"]).resolve(),
        umbral_inferior=float(inf),
        umbral_superior=float(sup),
        tamano_ventana=tam,
        minimo_puntuados=minimo,
        referencia=(base / data["referencia"]).resolve(),
        reglas=reglas,
        captura_zonas=tuple(cap["zonas"]),
        captura_errores=bool(cap["errores"]),
        captura_alertas=bool(cap["alertas"]),
        muestra_normal_cada=cap["muestra_normal_cada"],
        crudo=json.loads(json.dumps(data)),
    )


def cargar_referencia(ruta: Path) -> dict[str, Any] | None:
    """La referencia congelada, o None si aun no existe (la regla sostenida queda inactiva)."""
    if not ruta.is_file():
        return None
    data = json.loads(ruta.read_text(encoding="utf-8"))
    p = data.get("p_baja")
    if not (_num(p) and 0 <= p <= 1):
        raise ConfigError(f"{ruta}: p_baja de referencia invalida")
    return data
