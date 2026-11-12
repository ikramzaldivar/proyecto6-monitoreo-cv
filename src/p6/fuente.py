"""Fuente visual: reproduce una secuencia de imagenes como stream a ritmo fijo.

Un escenario (`escenarios/*.yaml`) enumera segmentos: imagenes de un manifiesto CSV
(`datos/carrito/capturas.csv` o uno de `datos/preparadas/`), opcionalmente filtradas por
secuencia, y pausas. Politica de muestreo: se emiten todos los frames listados, en orden,
uno cada `1/fps` segundos; no hay submuestreo. Una pausa detiene la emision ese tiempo
(simula una interrupcion de la camara).

El productor corre en un hilo y deja cada frame en una cola acotada. Si la cola esta
llena descarta el frame mas antiguo y lo cuenta como `descartado_saturacion`. El frame
lleva su hora de captura (reloj de pared UTC y `perf_counter`) para medir la espera en
cola y la latencia de extremo a extremo con el mismo reloj del proceso.
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Item:
    frame_id: str
    sequence_id: str
    ruta: Path
    sha256: str
    manifiesto: str
    pausa_antes_s: float = 0.0


@dataclass(frozen=True)
class Frame:
    seq: int
    item: Item
    t_captura_utc: str
    t_captura_perf: float


FIN = object()


def utc_iso(t: float | None = None) -> str:
    dt = datetime.fromtimestamp(time.time() if t is None else t, UTC)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def cargar_escenario(ruta: str | Path) -> tuple[dict[str, Any], list[Item]]:
    ruta = Path(ruta)
    data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    for clave in ("escenario_id", "descripcion", "segmentos"):
        if clave not in data:
            raise ValueError(f"{ruta}: falta {clave}")
    items: list[Item] = []
    pausa = 0.0
    for seg in data["segmentos"]:
        if "pausa_s" in seg:
            pausa += float(seg["pausa_s"])
            continue
        manifiesto = RAIZ / seg["manifiesto"]
        secuencias = seg.get("secuencias")
        with manifiesto.open(encoding="utf-8", newline="") as f:
            filas = list(csv.DictReader(f))
        filas = [r for r in filas if not secuencias or r["sequence_id"] in secuencias]
        if secuencias:  # respeta el orden pedido en el escenario
            filas.sort(key=lambda r: secuencias.index(r["sequence_id"]))
        for r in filas:
            items.append(
                Item(
                    frame_id=r["frame_id"],
                    sequence_id=r["sequence_id"],
                    ruta=manifiesto.parent / r["path"],
                    sha256=r["sha256"],
                    manifiesto=seg["manifiesto"],
                    pausa_antes_s=pausa,
                )
            )
            pausa = 0.0
    if not items:
        raise ValueError(f"{ruta}: el escenario no tiene frames")
    return data, items


class Productor(threading.Thread):
    """Emite los items a `fps` en una cola acotada con descarte del mas antiguo."""

    def __init__(self, items: list[Item], fps: float, cola_max: int) -> None:
        super().__init__(daemon=True, name="fuente")
        self.items = items
        self.periodo = 1.0 / fps
        self.cola: queue.Queue[Any] = queue.Queue(maxsize=cola_max)
        self.emitidos = 0
        self.descartados_saturacion = 0
        self._lock = threading.Lock()

    def _poner(self, frame: Any) -> None:
        while True:
            try:
                self.cola.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self.cola.get_nowait()
                    with self._lock:
                        self.descartados_saturacion += 1
                except queue.Empty:
                    pass

    def run(self) -> None:
        siguiente = time.perf_counter()
        for seq, item in enumerate(self.items, start=1):
            if item.pausa_antes_s:
                time.sleep(item.pausa_antes_s)
                siguiente = time.perf_counter()
            espera = siguiente - time.perf_counter()
            if espera > 0:
                time.sleep(espera)
            siguiente += self.periodo
            self._poner(Frame(seq, item, utc_iso(), time.perf_counter()))
            self.emitidos += 1
        self.cola.put(FIN)
