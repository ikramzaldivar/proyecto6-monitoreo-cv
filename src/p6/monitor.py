"""Monitor: fuente -> detector real -> evento -> captura -> ventana -> reglas -> alerta.

    python -m p6.monitor --escenario escenarios/c1-normal.yaml

Escribe una carpeta nueva `evidencias/corridas/<run_id>/` con:

- `run.json`: identidad de la corrida (escenario, revision Git, config, modelo, entorno);
- `config/`: copia exacta de monitoreo.yaml, detector.yaml, referencia.json y escenario;
- `eventos.jsonl`: un evento por frame procesado, escrito en cuanto termina su inferencia;
- `ventanas.jsonl`: conteos, p_baja y resultado de cada regla por ventana;
- `alertas.jsonl`: registro append-only de apertura, actualizacion y resolucion;
- `capturas.jsonl` e `imagenes/`: copias de las imagenes conservadas y su evento;
- `metricas.json`: indicadores calculados al final desde los JSONL (p6.metricas).

Nada se borra ni caduca: no existe codigo de limpieza de capturas.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from p6 import config as cfgmod
from p6 import metricas, politica, reglas
from p6.detector_onnx import DetectorError, DetectorONNX, cargar_config, sha256_archivo
from p6.fuente import FIN, RAIZ, Frame, Productor, cargar_escenario, utc_iso


def revision_git() -> dict[str, Any]:
    def git(*args: str) -> str:
        r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    estado = git("status", "--porcelain", "--untracked-files=no", "--", "src", "config", "escenarios")
    return {"commit": git("rev-parse", "HEAD") or None, "cambios_sin_commit_en_codigo": bool(estado)}


class Escritor:
    """JSONL append-only con flush por linea."""

    def __init__(self, ruta: Path) -> None:
        self._f = ruta.open("a", encoding="utf-8", newline="\n")

    def escribir(self, registro: dict[str, Any]) -> None:
        self._f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        self._f.flush()

    def cerrar(self) -> None:
        self._f.close()


class Monitor:
    def __init__(self, cfg: cfgmod.Config, escenario: dict[str, Any], salida: Path) -> None:
        self.cfg = cfg
        self.escenario = escenario
        self.det_cfg = cargar_config(cfg.detector)
        self.detector = DetectorONNX.desde_config(self.det_cfg)
        self.referencia = cfgmod.cargar_referencia(cfg.referencia)
        marca = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.run_id = f"{escenario['escenario_id']}-{marca}"
        self.dir = salida / self.run_id
        (self.dir / "imagenes").mkdir(parents=True, exist_ok=False)
        (self.dir / "config").mkdir()
        self.eventos = Escritor(self.dir / "eventos.jsonl")
        self.ventanas = Escritor(self.dir / "ventanas.jsonl")
        self.alertas = Escritor(self.dir / "alertas.jsonl")
        self.capturas = Escritor(self.dir / "capturas.jsonl")
        self.proceso = psutil.Process()
        self.proceso.cpu_percent(None)
        self.modelo = {
            "nombre": self.detector.nombre,
            "version": self._descriptor("version"),
            "archivo": self.det_cfg.modelo.name,
            "sha256": self.detector.model_sha256,
        }
        bc = cfg.reglas["cambio_sostenido"].parametros
        p_ref = self.referencia["p_baja"] if self.referencia else None
        self.sostenida = reglas.Sostenida(p_ref, bc["tolerancia"], int(bc["ventanas_consecutivas"]))
        self.ventana = self._nueva_ventana(1)
        self.abiertas: dict[str, dict[str, Any]] = {}  # regla -> alerta abierta
        self.n_alertas = 0
        self.eventos_por_id: dict[str, dict[str, Any]] = {}
        self.capturados: set[str] = set()
        self.n_normal = 0
        self.ultimo_frame_perf: float | None = None
        self.ultimo_evento: dict[str, Any] | None = None

    def _descriptor(self, clave: str) -> Any:
        import yaml

        return yaml.safe_load(self.det_cfg.descriptor.read_text(encoding="utf-8")).get(clave)

    def _nueva_ventana(self, indice: int) -> reglas.Ventana:
        return reglas.Ventana(f"{self.run_id}-v{indice:03d}", self.run_id, indice)

    # ---------------------------------------------------------------- identidad
    def escribir_run(self, items: list[Any], inicio: str, fin: str | None, extra: dict) -> None:
        for origen in (self.cfg.ruta, self.det_cfg.descriptor.parent / "descriptor.yaml"):
            shutil.copy2(origen, self.dir / "config" / origen.name)
        shutil.copy2(self.cfg.detector, self.dir / "config" / "detector.yaml")
        if self.cfg.referencia.is_file():
            shutil.copy2(self.cfg.referencia, self.dir / "config" / "referencia.json")
        import onnxruntime

        run = {
            "run_id": self.run_id,
            "escenario_id": self.escenario["escenario_id"],
            "escenario": self.escenario,
            "escenario_archivo": self.escenario.get("_archivo"),
            "inicio_utc": inicio,
            "fin_utc": fin,
            "git": revision_git(),
            "source_id": self.cfg.source_id,
            "task": "detection",
            "frames_planeados": len(items),
            "config_ref": self.cfg.config_ref,
            "config_sha256": self.cfg.sha256,
            "detector_config_sha256": self.det_cfg.config_sha256,
            "referencia": {
                "archivo": "config/referencia.json" if self.referencia else None,
                "sha256": sha256_archivo(self.cfg.referencia) if self.referencia else None,
                "run_id": self.referencia.get("run_id") if self.referencia else None,
                "p_baja": self.referencia.get("p_baja") if self.referencia else None,
            },
            "modelo": self.modelo,
            "politica": {
                "umbral_inferior": self.cfg.umbral_inferior,
                "umbral_superior": self.cfg.umbral_superior,
                "piso_salida": self.det_cfg.umbral_confianza,
                "nms_iou": self.det_cfg.nms_iou,
                "tamano_entrada": self.det_cfg.tamano_entrada,
            },
            "entorno": {
                "python": sys.version.split()[0],
                "onnxruntime": onnxruntime.__version__,
                "proveedor": "CPUExecutionProvider",
                "so": f"{platform.system()} {platform.release()} ({platform.version()})",
                "cpu": platform.processor(),
                "nucleos_logicos": os.cpu_count(),
                "ram_total_gb": round(psutil.virtual_memory().total / 2**30, 2),
            },
            **extra,
        }
        (self.dir / "run.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    # ---------------------------------------------------------------- capturas
    def capturar(self, evento: dict[str, Any], ruta: Path, motivo: str) -> str | None:
        if evento["event_id"] in self.capturados:
            return None
        destino = self.dir / "imagenes" / f"{evento['seq']:04d}_{evento['frame_id']}{ruta.suffix}"
        shutil.copyfile(ruta, destino)
        rel = destino.relative_to(self.dir).as_posix()
        self.capturados.add(evento["event_id"])
        self.capturas.escribir(
            {
                "capture_id": f"{evento['event_id']}-img",
                "event_id": evento["event_id"],
                "run_id": self.run_id,
                "timestamp": utc_iso(),
                "motivo": motivo,
                "image_ref": rel,
                "sha256": sha256_archivo(destino),
                "bytes": destino.stat().st_size,
                "expiracion": None,
            }
        )
        return rel

    def motivo_captura(self, evento: dict[str, Any]) -> str | None:
        if evento["status"] == "error":
            return "error" if self.cfg.captura_errores else None
        if evento["zona_frame"] in self.cfg.captura_zonas:
            return f"zona_{evento['zona_frame']}"
        self.n_normal += 1
        if (self.n_normal - 1) % self.cfg.muestra_normal_cada == 0:
            return "muestra_normal"
        return None

    # ---------------------------------------------------------------- frames
    def procesar(self, frame: Frame, cola_len: int) -> dict[str, Any]:
        item = frame.item
        t_inicio = time.perf_counter()
        base = {
            "event_id": f"{self.run_id}-f{frame.seq:04d}",
            "run_id": self.run_id,
            "seq": frame.seq,
            "frame_id": item.frame_id,
            "sequence_id": item.sequence_id,
            "source_id": self.cfg.source_id,
            "task": "detection",
            "entrada": {
                "manifiesto": item.manifiesto,
                "ruta": item.ruta.relative_to(RAIZ).as_posix(),
                "sha256_manifiesto": item.sha256,
            },
            "t_captura": frame.t_captura_utc,
            "model": self.modelo,
            "config_ref": self.cfg.config_ref,
            "umbrales": {
                "inferior": self.cfg.umbral_inferior,
                "superior": self.cfg.umbral_superior,
                "piso_salida": self.det_cfg.umbral_confianza,
            },
        }
        try:
            res = self.detector.detectar_imagen(item.ruta)
            dets = [
                d.a_dict()
                | {"zona": politica.zona(d.score, self.cfg.umbral_inferior, self.cfg.umbral_superior)}
                for d in res.detecciones
            ]
            score = politica.score_frame([d["score"] for d in dets])
            estado = {
                "status": "ok",
                "resultado": "con_detecciones" if dets else "sin_detecciones",
                "error": None,
                "imagen": {"ancho": res.ancho, "alto": res.alto},
                "detections": dets,
                "n_detecciones": len(dets),
                "score_frame": score,
                "zona_frame": politica.zona(score, self.cfg.umbral_inferior, self.cfg.umbral_superior),
                "tiempos_ms": {
                    "preproceso": round(res.preproceso_ms, 3),
                    "modelo": round(res.modelo_ms, 3),
                    "posproceso": round(res.posproceso_ms, 3),
                },
            }
        except DetectorError as exc:
            estado = {
                "status": "error",
                "resultado": None,
                "error": str(exc),
                "imagen": None,
                "detections": [],
                "n_detecciones": None,
                "score_frame": None,
                "zona_frame": None,
                "tiempos_ms": {"preproceso": None, "modelo": None, "posproceso": None},
            }
        t_fin = time.perf_counter()
        estado["tiempos_ms"] |= {
            "espera_cola": round((t_inicio - frame.t_captura_perf) * 1000, 3),
            "procesamiento": round((t_fin - t_inicio) * 1000, 3),
            "extremo_a_extremo": round((t_fin - frame.t_captura_perf) * 1000, 3),
        }
        evento = base | estado
        evento["timestamp"] = utc_iso()
        evento["ventana_id"] = self.ventana.ventana_id
        evento["recursos"] = {
            "rss_mb": round(self.proceso.memory_info().rss / 2**20, 2),
            "cpu_pct_proceso": self.proceso.cpu_percent(None),
            "cola_pendientes": cola_len,
        }
        evento["imagen_ref"] = None
        evento["motivo_captura"] = None
        if motivo := self.motivo_captura(evento):
            evento["imagen_ref"] = self.capturar(evento, item.ruta, motivo)
            evento["motivo_captura"] = motivo
        self.eventos.escribir(evento)
        self.eventos_por_id[evento["event_id"]] = {"ruta": item.ruta, **evento}
        self.ultimo_evento = evento
        self.ventana.eventos.append(evento)
        if len(self.ventana.eventos) >= self.cfg.tamano_ventana:
            self.cerrar_ventana()
        return evento

    # ---------------------------------------------------------------- reglas
    def cerrar_ventana(self) -> None:
        v = self.ventana
        if not v.eventos:
            return
        c = v.conteos()
        p = reglas.p_baja(c, self.cfg.minimo_puntuados)
        rb = self.cfg.reglas["baja_confianza"].parametros
        re_ = self.cfg.reglas["errores_inferencia"].parametros
        resultados = {
            "baja_confianza": reglas.evaluar_baja(p, rb["proporcion_minima"]),
            "cambio_sostenido": self.sostenida.evaluar(v.ventana_id, p),
            "errores_inferencia": reglas.evaluar_errores(c, re_["proporcion_minima"], re_["minimo_intentos"]),
        }
        racha = self.sostenida.ventanas_racha()
        for nombre, res in resultados.items():
            self._aplicar_regla(nombre, res, v, c, p, racha)
        self.ventanas.escribir(
            {
                "ventana_id": v.ventana_id,
                "run_id": self.run_id,
                "indice": v.indice,
                "desde": v.eventos[0]["timestamp"],
                "hasta": v.eventos[-1]["timestamp"],
                "event_ids": [e["event_id"] for e in v.eventos],
                "conteos": c,
                "p_baja": p,
                "estado": "suficiente" if p is not None else "insuficiente",
                "minimo_puntuados": self.cfg.minimo_puntuados,
                "p_baja_referencia": self.sostenida.p_referencia,
                "limite_sostenido": self.sostenida.limite,
                "racha_sostenida": racha,
                "reglas": resultados,
                "alertas_activas": sorted(a["alert_id"] for a in self.abiertas.values()),
                "n_alertas_activas": len(self.abiertas),
                "config_ref": self.cfg.config_ref,
                "evaluada_utc": utc_iso(),
            }
        )
        self.ventana = self._nueva_ventana(v.indice + 1)

    def _eventos_motivo(self, nombre: str, v: reglas.Ventana, racha: list[str]) -> list[str]:
        if nombre == "errores_inferencia":
            return [e["event_id"] for e in v.eventos if e["status"] == "error"]
        if nombre == "cambio_sostenido":
            return [
                eid
                for eid, e in self.eventos_por_id.items()
                if e["ventana_id"] in racha and e["zona_frame"] == politica.BAJA
            ]
        return [e["event_id"] for e in v.eventos if e["zona_frame"] == politica.BAJA]

    def _aplicar_regla(
        self,
        nombre: str,
        resultado: str,
        v: reglas.Ventana,
        c: dict[str, int],
        p: float | None,
        racha: list[str],
    ) -> None:
        regla = self.cfg.reglas[nombre]
        abierta = self.abiertas.get(nombre)
        ahora = utc_iso()
        if resultado == reglas.CUMPLE:
            eids = self._eventos_motivo(nombre, v, racha)
            observado = {"conteos": c, "p_baja": p}
            if nombre == "cambio_sostenido":
                observado |= {
                    "p_baja_referencia": self.sostenida.p_referencia,
                    "limite": self.sostenida.limite,
                    "ventanas_racha": racha,
                }
            if abierta is None:
                self.n_alertas += 1
                inicio = self.eventos_por_id[eids[0]]["t_captura"] if eids else v.eventos[0]["t_captura"]
                alerta = {
                    "registro": "apertura",
                    "alert_id": f"{self.run_id}-a{self.n_alertas:02d}",
                    "rule_id": regla.rule_id,
                    "regla": nombre,
                    "run_id": self.run_id,
                    "timestamp": ahora,
                    "severity": regla.severidad,
                    "estado": "abierta",
                    "reason": self._motivo(nombre, c, p),
                    "suggested_action": regla.accion,
                    "condicion": regla.parametros,
                    "observado": observado,
                    "ventana_ids": racha if nombre == "cambio_sostenido" else [v.ventana_id],
                    "event_ids": eids,
                    "inicio_condicion": inicio,
                    "config_ref": self.cfg.config_ref,
                }
                self.alertas.escribir(alerta)
                self.abiertas[nombre] = alerta
                self._capturar_alerta(eids)
            else:
                self.alertas.escribir(
                    {
                        "registro": "actualizacion",
                        "alert_id": abierta["alert_id"],
                        "rule_id": regla.rule_id,
                        "run_id": self.run_id,
                        "timestamp": ahora,
                        "ventana_ids": [v.ventana_id],
                        "event_ids": [e for e in eids if e not in abierta["event_ids"]],
                        "observado": observado,
                        "reason": self._motivo(nombre, c, p),
                    }
                )
                abierta["event_ids"] += [e for e in eids if e not in abierta["event_ids"]]
                self._capturar_alerta(eids)
        elif resultado == reglas.NO_CUMPLE and abierta is not None:
            self._resolver(nombre, v.ventana_id, self._motivo_resolucion(nombre, v.indice, c, p))

    def _motivo_resolucion(self, nombre: str, indice: int, c: dict[str, int], p: float | None) -> str:
        if nombre == "errores_inferencia":
            return (
                f"La ventana {indice} tiene {c['errores']} de {c['intentos']} frames con error: ya no cumple"
            )
        if nombre == "cambio_sostenido":
            return (
                f"La ventana {indice} tiene p_baja={p:.2f} <= limite {self.sostenida.limite:.3f}: "
                "se reinicia la racha"
            )
        umbral = self.cfg.reglas[nombre].parametros["proporcion_minima"]
        return f"La ventana {indice} tiene p_baja={p:.2f} < {umbral}: ya no cumple"

    def _resolver(self, nombre: str, ventana_id: str | None, motivo: str) -> None:
        abierta = self.abiertas.pop(nombre)
        self.alertas.escribir(
            {
                "registro": "resolucion",
                "alert_id": abierta["alert_id"],
                "rule_id": abierta["rule_id"],
                "run_id": self.run_id,
                "timestamp": utc_iso(),
                "ventana_ids": [ventana_id] if ventana_id else [],
                "reason": motivo,
            }
        )

    def _capturar_alerta(self, eids: list[str]) -> None:
        if not self.cfg.captura_alertas:
            return
        for eid in eids:
            e = self.eventos_por_id[eid]
            self.capturar(e, e["ruta"], "alerta")

    def _motivo(self, nombre: str, c: dict[str, int], p: float | None) -> str:
        if nombre == "baja_confianza":
            umbral = self.cfg.reglas[nombre].parametros["proporcion_minima"]
            return (
                f"{c['baja']} de {c['puntuados']} frames puntuados con s < "
                f"{self.cfg.umbral_inferior} (p_baja={p:.2f} >= {umbral})"
            )
        if nombre == "cambio_sostenido":
            k = int(self.cfg.reglas[nombre].parametros["ventanas_consecutivas"])
            return (
                f"p_baja={p:.2f} > referencia {self.sostenida.p_referencia:.3f} + tolerancia "
                f"{self.sostenida.tolerancia} durante {len(self.sostenida.racha)} ventanas "
                f"suficientes seguidas (minimo {k})"
            )
        return f"{c['errores']} de {c['intentos']} frames con status=error en la ventana"

    # ---------------------------------------------------------------- fuente
    def vigilar_fuente(self) -> None:
        if self.ultimo_frame_perf is None:
            return
        silencio = time.perf_counter() - self.ultimo_frame_perf
        if silencio <= self.cfg.limite_sin_frames_s or "fuente_detenida" in self.abiertas:
            return
        regla = self.cfg.reglas["fuente_detenida"]
        self.n_alertas += 1
        ult = self.ultimo_evento
        alerta = {
            "registro": "apertura",
            "alert_id": f"{self.run_id}-a{self.n_alertas:02d}",
            "rule_id": regla.rule_id,
            "regla": "fuente_detenida",
            "run_id": self.run_id,
            "timestamp": utc_iso(),
            "severity": regla.severidad,
            "estado": "abierta",
            "reason": (
                f"Sin frames nuevos de {self.cfg.source_id} durante {silencio:.1f} s "
                f"(limite {self.cfg.limite_sin_frames_s} s)"
            ),
            "suggested_action": regla.accion,
            "condicion": {"limite_sin_frames_s": self.cfg.limite_sin_frames_s},
            "observado": {"segundos_sin_frames": round(silencio, 3)},
            "ventana_ids": [self.ventana.ventana_id],
            "event_ids": [ult["event_id"]] if ult else [],
            "inicio_condicion": ult["t_captura"] if ult else None,
            "config_ref": self.cfg.config_ref,
        }
        self.alertas.escribir(alerta)
        self.abiertas["fuente_detenida"] = alerta
        self._capturar_alerta(alerta["event_ids"])

    # ---------------------------------------------------------------- bucle
    def ejecutar(self, items: list[Any]) -> Path:
        inicio = utc_iso()
        self.escribir_run(items, inicio, None, {"estado": "en_ejecucion"})
        productor = Productor(items, self.cfg.fps, self.cfg.cola_max)
        productor.start()
        procesados = 0
        while True:
            try:
                frame = productor.cola.get(timeout=0.1)
            except queue.Empty:
                self.vigilar_fuente()
                continue
            if frame is FIN:
                break
            if "fuente_detenida" in self.abiertas:
                self._resolver("fuente_detenida", None, "Se recibio un frame nuevo de la fuente")
            self.ultimo_frame_perf = time.perf_counter()
            self.procesar(frame, productor.cola.qsize())
            procesados += 1
        productor.join()
        self.cerrar_ventana()
        fin = utc_iso()
        for nombre in self.abiertas:
            self.alertas.escribir(
                {
                    "registro": "fin_corrida",
                    "alert_id": self.abiertas[nombre]["alert_id"],
                    "run_id": self.run_id,
                    "timestamp": fin,
                    "reason": "La corrida termino con la alerta abierta",
                }
            )
        for e in (self.eventos, self.ventanas, self.alertas, self.capturas):
            e.cerrar()
        self.escribir_run(
            items,
            inicio,
            fin,
            {
                "estado": "terminada",
                "fuente": {
                    "fps_configurado": self.cfg.fps,
                    "frames_emitidos": productor.emitidos,
                    "frames_procesados": procesados,
                    "descartados_saturacion": productor.descartados_saturacion,
                },
                "alertas_abiertas_al_final": sorted(a["alert_id"] for a in self.abiertas.values()),
            },
        )
        metricas.escribir(self.dir)
        return self.dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escenario", required=True, type=Path)
    ap.add_argument("--config", default=RAIZ / "config" / "monitoreo.yaml", type=Path)
    ap.add_argument("--salida", default=RAIZ / "evidencias" / "corridas", type=Path)
    args = ap.parse_args(argv)
    cfg = cfgmod.cargar(args.config)
    escenario, items = cargar_escenario(args.escenario)
    escenario["_archivo"] = args.escenario.resolve().relative_to(RAIZ).as_posix()
    mon = Monitor(cfg, escenario, args.salida.resolve())
    shutil.copy2(args.escenario, mon.dir / "config" / args.escenario.name)
    print(f"run_id={mon.run_id} frames={len(items)} fps={cfg.fps} config={cfg.config_ref}")
    salida = mon.ejecutar(items)
    resumen = json.loads((salida / "metricas.json").read_text(encoding="utf-8"))["resumen"]
    print(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f"evidencias en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
