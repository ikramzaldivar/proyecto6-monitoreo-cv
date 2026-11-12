"""Indice SQLite del portal, reconstruido desde los archivos primarios de cada corrida.

Los JSONL de `evidencias/corridas/<run_id>/` son la persistencia primaria (append-only,
versionados en Git). El portal los carga en `evidencias/portal.sqlite` para consultarlos
con filtros; el archivo SQLite se puede borrar y regenerar en cualquier momento. Las
revisiones manuales de capturas se guardan en `evidencias/revisiones.jsonl` y tambien se
cargan aqui.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from p6.metricas import leer_jsonl

ESQUEMA = """
CREATE TABLE corridas (
  run_id TEXT PRIMARY KEY, escenario_id TEXT, inicio TEXT, fin TEXT, estado TEXT,
  config_ref TEXT, commit_git TEXT, run_json TEXT, metricas_json TEXT);
CREATE TABLE eventos (
  event_id TEXT PRIMARY KEY, run_id TEXT, seq INTEGER, frame_id TEXT, sequence_id TEXT,
  source_id TEXT, timestamp TEXT, status TEXT, resultado TEXT, score REAL, zona TEXT,
  clase_top TEXT, n_detecciones INTEGER, ventana_id TEXT, imagen_ref TEXT,
  motivo_captura TEXT, modelo TEXT, config_ref TEXT, error TEXT, json TEXT);
CREATE INDEX ev_run ON eventos(run_id, seq);
CREATE TABLE detecciones (
  event_id TEXT, run_id TEXT, clase TEXT, score REAL, zona TEXT);
CREATE TABLE ventanas (
  ventana_id TEXT PRIMARY KEY, run_id TEXT, indice INTEGER, estado TEXT, p_baja REAL,
  n_alertas_activas INTEGER, json TEXT);
CREATE TABLE alertas (
  alert_id TEXT PRIMARY KEY, run_id TEXT, rule_id TEXT, regla TEXT, severidad TEXT,
  estado TEXT, abierta TEXT, resuelta TEXT, motivo TEXT, accion TEXT, config_ref TEXT,
  n_eventos INTEGER, json TEXT, registros TEXT);
CREATE TABLE alerta_evento (alert_id TEXT, event_id TEXT);
CREATE TABLE alerta_ventana (alert_id TEXT, ventana_id TEXT);
CREATE TABLE capturas (
  capture_id TEXT PRIMARY KEY, event_id TEXT, run_id TEXT, timestamp TEXT, motivo TEXT,
  image_ref TEXT, sha256 TEXT, existe INTEGER);
CREATE TABLE revisiones (
  revision_id TEXT PRIMARY KEY, capture_id TEXT, event_id TEXT, timestamp TEXT,
  veredicto TEXT, nota TEXT);
"""


def conectar(ruta: Path) -> sqlite3.Connection:
    con = sqlite3.connect(ruta, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def reconstruir(corridas: Path, ruta_db: Path, revisiones: Path) -> sqlite3.Connection:
    if ruta_db.exists():
        ruta_db.unlink()
    con = conectar(ruta_db)
    con.executescript(ESQUEMA)
    for dir_run in sorted(p for p in corridas.iterdir() if (p / "run.json").is_file()):
        cargar_corrida(con, dir_run)
    for r in leer_jsonl(revisiones):
        guardar_revision(con, r)
    con.commit()
    return con


def cargar_corrida(con: sqlite3.Connection, d: Path) -> None:
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    met = d / "metricas.json"
    con.execute(
        "INSERT INTO corridas VALUES (?,?,?,?,?,?,?,?,?)",
        (
            run["run_id"],
            run["escenario_id"],
            run["inicio_utc"],
            run["fin_utc"],
            run["estado"],
            run["config_ref"],
            (run.get("git") or {}).get("commit"),
            json.dumps(run, ensure_ascii=False),
            met.read_text(encoding="utf-8") if met.is_file() else None,
        ),
    )
    for e in leer_jsonl(d / "eventos.jsonl"):
        top = e["detections"][0]["class_name"] if e["detections"] else None
        con.execute(
            "INSERT INTO eventos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                e["event_id"],
                e["run_id"],
                e["seq"],
                e["frame_id"],
                e["sequence_id"],
                e["source_id"],
                e["timestamp"],
                e["status"],
                e["resultado"],
                e["score_frame"],
                e["zona_frame"],
                top,
                e["n_detecciones"],
                e["ventana_id"],
                e["imagen_ref"],
                e["motivo_captura"],
                f"{e['model']['nombre']}@{e['model']['sha256'][:12]}",
                e["config_ref"],
                e["error"],
                json.dumps(e, ensure_ascii=False),
            ),
        )
        con.executemany(
            "INSERT INTO detecciones VALUES (?,?,?,?,?)",
            [(e["event_id"], e["run_id"], x["class_name"], x["score"], x["zona"]) for x in e["detections"]],
        )
    for v in leer_jsonl(d / "ventanas.jsonl"):
        con.execute(
            "INSERT INTO ventanas VALUES (?,?,?,?,?,?,?)",
            (
                v["ventana_id"],
                v["run_id"],
                v["indice"],
                v["estado"],
                v["p_baja"],
                v["n_alertas_activas"],
                json.dumps(v, ensure_ascii=False),
            ),
        )
    registros: dict[str, list[dict[str, Any]]] = {}
    for a in leer_jsonl(d / "alertas.jsonl"):
        registros.setdefault(a["alert_id"], []).append(a)
    for alert_id, regs in registros.items():
        ap = regs[0]
        eids = list(ap["event_ids"])
        vids = list(ap["ventana_ids"])
        resuelta = None
        for r in regs[1:]:
            eids += [x for x in r.get("event_ids", []) if x not in eids]
            vids += [x for x in r.get("ventana_ids", []) if x not in vids]
            if r["registro"] == "resolucion":
                resuelta = r["timestamp"]
        con.execute(
            "INSERT INTO alertas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                alert_id,
                ap["run_id"],
                ap["rule_id"],
                ap["regla"],
                ap["severity"],
                "resuelta" if resuelta else "abierta",
                ap["timestamp"],
                resuelta,
                ap["reason"],
                ap["suggested_action"],
                ap["config_ref"],
                len(eids),
                json.dumps(ap, ensure_ascii=False),
                json.dumps(regs, ensure_ascii=False),
            ),
        )
        con.executemany("INSERT INTO alerta_evento VALUES (?,?)", [(alert_id, x) for x in eids])
        con.executemany("INSERT INTO alerta_ventana VALUES (?,?)", [(alert_id, x) for x in vids])
    for c in leer_jsonl(d / "capturas.jsonl"):
        con.execute(
            "INSERT INTO capturas VALUES (?,?,?,?,?,?,?,?)",
            (
                c["capture_id"],
                c["event_id"],
                c["run_id"],
                c["timestamp"],
                c["motivo"],
                c["image_ref"],
                c["sha256"],
                int((d / c["image_ref"]).is_file()),
            ),
        )


def guardar_revision(con: sqlite3.Connection, r: dict[str, Any]) -> None:
    con.execute(
        "INSERT OR REPLACE INTO revisiones VALUES (?,?,?,?,?,?)",
        (r["revision_id"], r["capture_id"], r["event_id"], r["timestamp"], r["veredicto"], r["nota"]),
    )
