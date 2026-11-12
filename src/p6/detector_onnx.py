"""Detector YOLOX-Nano en ONNX Runtime CPU, reutilizado del Proyecto 5.

Origen: `Proyecto5/src/p5/detector_onnx.py` del repositorio del equipo
(sebastian0023/Proyecto-3-Clasificador-de-imagenes, commit b63ddbc), autora original Edith
(P5-04, #56). Cambios para P6: `Deteccion` propia en lugar de `p5.contrato.Detection`, se
quita la interfaz `detectar(frame)` del recorrido de P5 y `detectar_imagen` devuelve
ademas los tiempos de preproceso, `session.run` y posproceso (`time.perf_counter`).

Preprocesamiento (letterbox de YOLOX): la imagen RGB se escala por
`r = min(S/H, S/W)` con Pillow BILINEAR, se pega arriba a la izquierda en un lienzo SxS
gris `relleno` y se pasa a BGR, NCHW, float32 0-255 sin normalizar.

Posprocesamiento: se decodifica la rejilla (strides 8/16/32), `score = objectness x
prob_clase` con la mejor clase por ancla, se descarta lo menor a `umbral_confianza` (el
piso de salida, por debajo del umbral inferior de la politica para poder observar la zona
de baja confianza), NMS por clase con `nms_iou`, cajas `xyxy` en pixeles del cuadro.

Fallos: imagen ilegible, salida con forma inesperada o valores no finitos levantan
`DetectorError`; el monitor lo registra como `status=error`.
Pesos con otro SHA-256 o config invalida levantan `ModeloInvalidoError` al cargar.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import yaml
from PIL import Image

STRIDES = (8, 16, 32)
NOMBRE = "yolox_nano"


@dataclass(frozen=True)
class Deteccion:
    class_name: str
    class_id: int
    score: float
    bbox_xyxy: tuple[float, float, float, float]

    def a_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "class_id": self.class_id,
            "score": round(self.score, 6),
            "bbox_xyxy": list(self.bbox_xyxy),
        }


@dataclass(frozen=True)
class Resultado:
    ancho: int
    alto: int
    detecciones: list[Deteccion]
    preproceso_ms: float
    modelo_ms: float
    posproceso_ms: float


class DetectorError(RuntimeError):
    """Un cuadro no se pudo procesar; el recorrido lo registra como `status=error`."""


class ModeloInvalidoError(ValueError):
    """Configuracion, pesos o descriptor rechazados al cargar el detector."""


class Sesion(Protocol):
    """Lo que se usa de `onnxruntime.InferenceSession` (inyectable en pruebas)."""

    def run(self, output_names: Any, input_feed: dict[str, np.ndarray]) -> list[np.ndarray]: ...


@dataclass(frozen=True)
class ConfigDetector:
    modelo: Path
    descriptor: Path
    tamano_entrada: int
    relleno: int
    umbral_confianza: float
    nms_iou: float
    max_detecciones: int
    config_sha256: str


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(1 << 20):
            h.update(bloque)
    return h.hexdigest()


def _numero(seccion: dict[str, Any], clave: str, errores: list[str], tipo: type) -> Any:
    valor = seccion.get(clave)
    if tipo is int and (isinstance(valor, bool) or not isinstance(valor, int)):
        errores.append(f"{clave} debe ser entero")
        return None
    if tipo is float and (isinstance(valor, bool) or not isinstance(valor, int | float)):
        errores.append(f"{clave} debe ser numero")
        return None
    if tipo is float and not math.isfinite(valor):
        errores.append(f"{clave} debe ser finito")
        return None
    return valor


def cargar_config(ruta: Path, modelo: Path | None = None) -> ConfigDetector:
    """Lee `config/detector.yaml`; rutas relativas al archivo. `modelo` reemplaza la del YAML."""
    ruta = Path(ruta)
    try:
        data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModeloInvalidoError(f"{ruta}: {exc}") from exc
    if not isinstance(data, dict):
        raise ModeloInvalidoError(f"{ruta}: se esperaba un mapa")
    errores: list[str] = []
    claves = {"version", "modelo", "descriptor", "preprocesamiento", "posprocesamiento"}
    if extra := set(data) - claves:
        errores.append(f"claves desconocidas {sorted(extra)}")
    if data.get("version") != 1:
        errores.append("version debe ser 1")
    pre = data.get("preprocesamiento") or {}
    pos = data.get("posprocesamiento") or {}
    if extra := set(pre) - {"tamano_entrada", "relleno"}:
        errores.append(f"preprocesamiento: claves desconocidas {sorted(extra)}")
    if extra := set(pos) - {"umbral_confianza", "nms_iou", "max_detecciones"}:
        errores.append(f"posprocesamiento: claves desconocidas {sorted(extra)}")
    tamano = _numero(pre, "tamano_entrada", errores, int)
    relleno = _numero(pre, "relleno", errores, int)
    umbral = _numero(pos, "umbral_confianza", errores, float)
    iou = _numero(pos, "nms_iou", errores, float)
    maximo = _numero(pos, "max_detecciones", errores, int)
    if tamano is not None and (tamano <= 0 or tamano % 32):
        errores.append("tamano_entrada debe ser positivo y multiplo de 32")
    if relleno is not None and not 0 <= relleno <= 255:
        errores.append("relleno debe estar en [0, 255]")
    if umbral is not None and not 0 < umbral <= 1:
        errores.append("umbral_confianza debe estar en (0, 1]")
    if iou is not None and not 0 < iou <= 1:
        errores.append("nms_iou debe estar en (0, 1]")
    if maximo is not None and maximo <= 0:
        errores.append("max_detecciones debe ser positivo")
    for clave in ("modelo", "descriptor"):
        if not isinstance(data.get(clave), str) or not data[clave]:
            errores.append(f"{clave} debe ser una ruta")
    if errores:
        raise ModeloInvalidoError(f"{ruta}: " + "; ".join(errores))
    base = ruta.resolve().parent
    return ConfigDetector(
        modelo=Path(modelo) if modelo is not None else base / data["modelo"],
        descriptor=base / data["descriptor"],
        tamano_entrada=tamano,
        relleno=relleno,
        umbral_confianza=float(umbral),
        nms_iou=float(iou),
        max_detecciones=maximo,
        config_sha256=sha256_archivo(ruta),
    )


def leer_imagen(ruta: str | Path) -> np.ndarray:
    """Decodifica la imagen completa a RGB uint8 HxWx3; si no se puede, `DetectorError`."""
    try:
        with Image.open(ruta) as im:
            im.load()
            return np.asarray(im.convert("RGB"))
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise DetectorError(f"imagen ilegible: {type(exc).__name__}: {exc}") from exc


def letterbox(rgb: np.ndarray, tamano: int, relleno: int) -> tuple[np.ndarray, float]:
    """Tensor NCHW BGR float32 y la escala `r` para regresar al cuadro original."""
    alto, ancho = rgb.shape[:2]
    r = min(tamano / alto, tamano / ancho)
    nuevo_ancho, nuevo_alto = int(ancho * r), int(alto * r)
    escalada = Image.fromarray(rgb).resize((nuevo_ancho, nuevo_alto), Image.BILINEAR)
    lienzo = np.full((tamano, tamano, 3), relleno, dtype=np.uint8)
    lienzo[:nuevo_alto, :nuevo_ancho] = np.asarray(escalada)
    bgr = lienzo[:, :, ::-1]
    return np.ascontiguousarray(bgr.transpose(2, 0, 1)[None], dtype=np.float32), r


def _rejilla(tamano: int) -> tuple[np.ndarray, np.ndarray]:
    rejillas, strides = [], []
    for stride in STRIDES:
        lado = tamano // stride
        yv, xv = np.meshgrid(np.arange(lado), np.arange(lado), indexing="ij")
        rejillas.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((lado * lado, 1), stride))
    return np.concatenate(rejillas).astype(np.float32), np.concatenate(strides).astype(np.float32)


def nms(cajas: np.ndarray, scores: np.ndarray, iou_max: float) -> list[int]:
    """Indices que sobreviven al NMS, en orden de confianza descendente."""
    orden = scores.argsort()[::-1]
    areas = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
    quedan: list[int] = []
    while orden.size:
        i = int(orden[0])
        quedan.append(i)
        resto = orden[1:]
        x1 = np.maximum(cajas[i, 0], cajas[resto, 0])
        y1 = np.maximum(cajas[i, 1], cajas[resto, 1])
        x2 = np.minimum(cajas[i, 2], cajas[resto, 2])
        y2 = np.minimum(cajas[i, 3], cajas[resto, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou = inter / np.maximum(areas[i] + areas[resto] - inter, 1e-9)
        orden = resto[iou <= iou_max]
    return quedan


def decodificar(
    salida: np.ndarray,
    r: float,
    ancho: int,
    alto: int,
    config: ConfigDetector,
    clases: list[str],
) -> list[Deteccion]:
    """Salida cruda `[1, N, 5 + C]` de YOLOX a detecciones en pixeles del cuadro original."""
    anclas = sum((config.tamano_entrada // s) ** 2 for s in STRIDES)
    esperada = (1, anclas, 5 + len(clases))
    if salida.shape != esperada:
        raise DetectorError(f"salida malformada: forma {salida.shape}, se esperaba {esperada}")
    if not np.isfinite(salida).all():
        raise DetectorError("salida no finita del modelo (NaN o infinito)")
    o = salida[0].astype(np.float64)
    rejilla, strides = _rejilla(config.tamano_entrada)
    centro = (o[:, :2] + rejilla) * strides
    with np.errstate(over="ignore"):
        lados = np.exp(o[:, 2:4]) * strides
    cajas = np.concatenate((centro - lados / 2, centro + lados / 2), axis=1) / r
    por_clase = o[:, 4:5] * o[:, 5:]
    clase = por_clase.argmax(1)
    score = por_clase.max(1)
    sel = score >= config.umbral_confianza
    cajas, clase, score = cajas[sel], clase[sel], score[sel]
    if not np.isfinite(cajas).all() or not np.isfinite(score).all():
        raise DetectorError("salida no finita al decodificar las cajas")
    cajas[:, [0, 2]] = cajas[:, [0, 2]].clip(0, ancho)
    cajas[:, [1, 3]] = cajas[:, [1, 3]].clip(0, alto)
    detecciones: list[Deteccion] = []
    for c in np.unique(clase):
        idx = np.flatnonzero(clase == c)
        for k in nms(cajas[idx], score[idx], config.nms_iou):
            x1, y1, x2, y2 = (round(float(v), 2) for v in cajas[idx[k]])
            if x1 < x2 and y1 < y2:
                conf = min(max(float(score[idx[k]]), 0.0), 1.0)
                detecciones.append(Deteccion(clases[int(c)], int(c), conf, (x1, y1, x2, y2)))
    detecciones.sort(key=lambda d: d.score, reverse=True)
    return detecciones[: config.max_detecciones]


class DetectorONNX:
    """Detector YOLOX-Nano; `desde_config` verifica el SHA-256 y abre la sesion de CPU."""

    nombre = NOMBRE
    synthetic = False

    def __init__(
        self,
        sesion: Sesion,
        config: ConfigDetector,
        clases: list[str],
        model_sha256: str,
        nombre_entrada: str = "images",
    ) -> None:
        self._sesion = sesion
        self.config = config
        self.clases = clases
        self.model_sha256 = model_sha256
        self._entrada = nombre_entrada

    @classmethod
    def desde_config(cls, config: ConfigDetector) -> DetectorONNX:
        try:
            descriptor = yaml.safe_load(config.descriptor.read_text(encoding="utf-8"))
            esperado, clases = str(descriptor["sha256"]), list(descriptor["clases"])
        except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
            raise ModeloInvalidoError(f"descriptor {config.descriptor}: {exc}") from exc
        if not config.modelo.is_file():
            raise ModeloInvalidoError(
                f"no existe {config.modelo}; descargalo con "
                "`python scripts/descargar_modelo.py --destino modelo/`"
            )
        obtenido = sha256_archivo(config.modelo)
        if obtenido != esperado:
            raise ModeloInvalidoError(
                f"SHA-256 de {config.modelo} es {obtenido}; el descriptor espera {esperado}"
            )
        import onnxruntime as ort  # solo al cargar pesos reales: las pruebas inyectan sesion

        try:
            sesion = ort.InferenceSession(str(config.modelo), providers=["CPUExecutionProvider"])
        except Exception as exc:  # ONNX Runtime no expone una jerarquia de errores estable
            raise ModeloInvalidoError(f"onnxruntime no pudo cargar {config.modelo}: {exc}") from exc
        entrada = sesion.get_inputs()[0]
        lado = config.tamano_entrada
        if list(entrada.shape) != [1, 3, lado, lado]:
            raise ModeloInvalidoError(f"entrada del modelo {entrada.shape}, config pide {lado}")
        return cls(sesion, config, clases, obtenido, entrada.name)

    def detectar_imagen(self, ruta: str | Path) -> Resultado:
        """Detecciones del cuadro completo en `ruta` y tiempos de cada etapa (ms)."""
        t0 = time.perf_counter()
        rgb = leer_imagen(ruta)
        alto, ancho = rgb.shape[:2]
        tensor, r = letterbox(rgb, self.config.tamano_entrada, self.config.relleno)
        t1 = time.perf_counter()
        try:
            salida = self._sesion.run(None, {self._entrada: tensor})[0]
        except Exception as exc:  # cualquier fallo del runtime es un fallo del detector
            raise DetectorError(f"onnxruntime: {type(exc).__name__}: {exc}") from exc
        t2 = time.perf_counter()
        detecciones = decodificar(np.asarray(salida), r, ancho, alto, self.config, self.clases)
        t3 = time.perf_counter()
        return Resultado(
            ancho,
            alto,
            detecciones,
            preproceso_ms=(t1 - t0) * 1000,
            modelo_ms=(t2 - t1) * 1000,
            posproceso_ms=(t3 - t2) * 1000,
        )
