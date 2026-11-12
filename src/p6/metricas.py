"""Metricas de una corrida, calculadas solo desde sus archivos primarios.

    python -m p6.metricas evidencias/corridas/<run_id>

Lee `run.json`, `eventos.jsonl`, `ventanas.jsonl`, `alertas.jsonl`, `capturas.jsonl` y
`config/` de la corrida y escribe `metricas.json`. Las definiciones (unidad, formula,
poblacion, ventana, exclusiones y cero observaciones) estan en docs/metricas.md; cada
indicador incluye `n` (tamano de la poblacion) y vale null cuando la poblacion esta vacia,
con `motivo_null`. Nunca se reporta 0 por falta de datos.

Percentiles: metodo nearest-rank (el valor en la posicion ceil(q*n) de la lista
ordenada), sin interpolacion, para que se pueda recalcular a mano.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[2]

# Cortes de la distribucion de puntuacion del frame (piso de salida 0.10 hasta 1.0].
BINS = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85, 1.0000001)
EPS_PSI = 1e-4
CAMPOS_TRAZA = (
    "event_id",
    "run_id",
    "frame_id",
    "timestamp",
    "source_id",
    "model",
    "status",
    "config_ref",
    "ventana_id",
    "entrada",
)


def leer_jsonl(ruta: Path) -> list[dict[str, Any]]:
    if not ruta.is_file():
        return []
    with ruta.open(encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def ts(valor: str) -> float:
    return datetime.fromisoformat(valor.replace("Z", "+00:00")).timestamp()


def percentil(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    orden = sorted(valores)
    return orden[max(1, math.ceil(q * len(orden))) - 1]


def _nulo(motivo: str, **extra: Any) -> dict[str, Any]:
    return {"valor": None, "motivo_null": motivo, **extra}


def distribucion(scores: list[float]) -> list[int]:
    cuentas = [0] * (len(BINS) - 1)
    for s in scores:
        for i in range(len(BINS) - 1):
            if BINS[i] <= s < BINS[i + 1]:
                cuentas[i] += 1
                break
    return cuentas


def psi(actual: list[int], referencia: list[int]) -> float | None:
    na, nr = sum(actual), sum(referencia)
    if na == 0 or nr == 0:
        return None
    total = 0.0
    for a, r in zip(actual, referencia, strict=True):
        pa, pr = max(a / na, EPS_PSI), max(r / nr, EPS_PSI)
        total += (pa - pr) * math.log(pa / pr)
    return total


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def calcular(dir_run: Path) -> dict[str, Any]:
    run = json.loads((dir_run / "run.json").read_text(encoding="utf-8"))
    eventos = leer_jsonl(dir_run / "eventos.jsonl")
    ventanas = leer_jsonl(dir_run / "ventanas.jsonl")
    alertas = leer_jsonl(dir_run / "alertas.jsonl")
    capturas = leer_jsonl(dir_run / "capturas.jsonl")
    ok = [e for e in eventos if e["status"] == "ok"]
    puntuados = [e for e in ok if e["score_frame"] is not None]
    n = len(eventos)
    m: dict[str, Any] = {}

    # G1 base: tiempo de inferencia del modelo (session.run), ms, frames status=ok.
    t_modelo = [e["tiempos_ms"]["modelo"] for e in ok]
    m["G1_tiempo_inferencia_ms"] = (
        {"p50": percentil(t_modelo, 0.5), "p95": percentil(t_modelo, 0.95), "n": len(t_modelo)}
        if t_modelo
        else _nulo("sin frames con status=ok", n=0)
    )
    # G1 adicional: tasa de errores tecnicos = status=error / frames procesados.
    m["G1x_tasa_errores"] = (
        {"valor": sum(e["status"] == "error" for e in eventos) / n, "n": n}
        if n
        else _nulo("sin frames procesados", n=0)
    )

    # G2 base: FPS de procesamiento = frames procesados / segundos entre la captura del
    # primero y el registro del ultimo evento.
    if n >= 2:
        dur = ts(eventos[-1]["timestamp"]) - ts(eventos[0]["t_captura"])
        m["G2_fps_procesamiento"] = {"valor": n / dur, "n": n, "duracion_s": dur}
    else:
        m["G2_fps_procesamiento"] = _nulo("se requieren al menos 2 frames procesados", n=n)
    # G2 adicional: latencia de extremo a extremo (captura -> evento registrado), ms.
    e2e = [e["tiempos_ms"]["extremo_a_extremo"] for e in eventos]
    m["G2x_latencia_e2e_ms"] = (
        {"p50": percentil(e2e, 0.5), "p95": percentil(e2e, 0.95), "max": max(e2e), "n": len(e2e)}
        if e2e
        else _nulo("sin frames procesados", n=0)
    )
    # G2 adicional: frames descartados por la aplicacion (saturacion de la cola).
    fuente = run.get("fuente") or {}
    m["G2x_descartados"] = {
        "saturacion": fuente.get("descartados_saturacion"),
        "muestreo": 0,
        "emitidos": fuente.get("frames_emitidos"),
        "procesados": fuente.get("frames_procesados"),
    }

    # G3 base: memoria residente (RSS) del proceso del monitor, MB, una muestra por frame.
    rss = [e["recursos"]["rss_mb"] for e in eventos]
    m["G3_rss_mb"] = (
        {"max": max(rss), "media": sum(rss) / len(rss), "n": len(rss)} if rss else _nulo("sin muestras", n=0)
    )
    # G3 adicional: CPU del proceso (% de un nucleo, psutil, desde la muestra anterior).
    cpu = [e["recursos"]["cpu_pct_proceso"] for e in eventos[1:]]
    m["G3x_cpu_pct_proceso"] = (
        {"media": sum(cpu) / len(cpu), "max": max(cpu), "n": len(cpu)}
        if cpu
        else _nulo("se requiere mas de una muestra", n=len(cpu))
    )

    # G4 base: proporcion de baja confianza = frames zona baja / frames puntuados.
    zonas = Counter(e["zona_frame"] for e in puntuados)
    m["G4_p_baja"] = (
        {"valor": zonas["baja"] / len(puntuados), "baja": zonas["baja"], "n": len(puntuados)}
        if puntuados
        else _nulo("sin frames puntuados", n=0)
    )
    m["G4_zonas"] = {
        "aceptada": zonas["aceptada"],
        "duda": zonas["duda"],
        "baja": zonas["baja"],
        "sin_detecciones": sum(e["score_frame"] is None for e in ok),
        "error": n - len(ok),
    }
    # G4 adicional: frames sin detecciones / frames status=ok.
    sin = m["G4_zonas"]["sin_detecciones"]
    m["G4x_sin_detecciones"] = (
        {"valor": sin / len(ok), "sin_detecciones": sin, "n": len(ok)}
        if ok
        else _nulo("sin frames status=ok", n=0)
    )
    # G4 adicional: predicciones por clase (unidad: deteccion candidata) por zona.
    por_clase: dict[str, Counter] = {}
    for e in ok:
        for d in e["detections"]:
            por_clase.setdefault(d["class_name"], Counter())[d["zona"]] += 1
    m["G4x_detecciones_por_clase"] = {
        k: dict(v) | {"total": sum(v.values())}
        for k, v in sorted(por_clase.items(), key=lambda kv: -sum(kv[1].values()))
    }
    # G4 adicional: distribucion de score_frame comparada con la referencia (PSI).
    dist = distribucion([e["score_frame"] for e in puntuados])
    ref_ruta = dir_run / "config" / "referencia.json"
    ref = json.loads(ref_ruta.read_text(encoding="utf-8")) if ref_ruta.is_file() else None
    if ref is None:
        m["G4x_psi_referencia"] = _nulo("la corrida no tenia referencia", distribucion=dist)
    elif not puntuados:
        m["G4x_psi_referencia"] = _nulo("sin frames puntuados", distribucion=dist)
    else:
        m["G4x_psi_referencia"] = {
            "valor": psi(dist, ref["distribucion"]),
            "bins": list(BINS[:-1]) + [1.0],
            "distribucion": dist,
            "distribucion_referencia": ref["distribucion"],
            "n": len(puntuados),
            "n_referencia": sum(ref["distribucion"]),
        }

    # G5 base: imagenes vinculadas = capturas cuyo archivo existe, coincide su SHA-256 y su
    # event_id existe en eventos.jsonl / capturas registradas.
    ids = {e["event_id"] for e in eventos}
    detalle = []
    for c in capturas:
        ruta = dir_run / c["image_ref"]
        valida = ruta.is_file() and sha256(ruta) == c["sha256"] and c["event_id"] in ids
        detalle.append(valida)
    m["G5_imagenes_vinculadas"] = (
        {"valor": sum(detalle) / len(detalle), "vinculadas": sum(detalle), "n": len(detalle)}
        if detalle
        else _nulo("la corrida no registro capturas", n=0)
    )
    # G5 adicional: cobertura de trazabilidad = eventos con todos los campos requeridos y
    # cuya entrada coincide con el SHA-256 del manifiesto / eventos. Las rutas de entrada son
    # relativas a la raiz del repositorio, no a la carpeta de la corrida (puede estar fuera).
    raiz = RAIZ
    completos = 0
    for e in eventos:
        campos = all(e.get(k) not in (None, "") for k in CAMPOS_TRAZA)
        entrada = raiz / e["entrada"]["ruta"]
        integra = entrada.is_file() and sha256(entrada) == e["entrada"]["sha256_manifiesto"]
        completos += campos and integra
    m["G5x_cobertura_trazabilidad"] = (
        {"valor": completos / n, "completos": completos, "n": n} if n else _nulo("sin eventos", n=0)
    )

    # G6 base: version esperada frente a reportada = eventos cuyo model.sha256 es el del
    # descriptor congelado de la corrida / eventos.
    desc = (dir_run / "config" / "descriptor.yaml").read_text(encoding="utf-8")
    esperado = next(
        linea.split(":", 1)[1].strip() for linea in desc.splitlines() if linea.startswith("sha256:")
    )
    versiones = Counter(f"{e['model']['nombre']}@{e['model']['sha256'][:12]}" for e in eventos)
    coinciden = sum(e["model"]["sha256"] == esperado for e in eventos)
    m["G6_version_esperada_vs_reportada"] = (
        {
            "valor": coinciden / n,
            "coinciden": coinciden,
            "n": n,
            "esperada": esperado,
            "distribucion": dict(versiones),
        }
        if n
        else _nulo("sin eventos", n=0)
    )
    # G6 adicional: reportes por fuente y tiempo desde el ultimo reporte al cierre.
    por_fuente = Counter(e["source_id"] for e in eventos)
    fin = run.get("fin_utc")
    m["G6x_reportes_por_fuente"] = {
        k: {
            "reportes": v,
            "s_desde_ultimo_al_cierre": (
                ts(fin) - ts([e for e in eventos if e["source_id"] == k][-1]["timestamp"]) if fin else None
            ),
        }
        for k, v in por_fuente.items()
    }

    # G7 base: alertas activas por ventana (abiertas al cerrar cada ventana).
    serie = [v["n_alertas_activas"] for v in ventanas]
    aperturas = [a for a in alertas if a["registro"] == "apertura"]
    resoluciones = {a["alert_id"] for a in alertas if a["registro"] == "resolucion"}
    m["G7_alertas_activas"] = (
        {
            "max_por_ventana": max(serie),
            "al_cierre": len([a for a in aperturas if a["alert_id"] not in resoluciones]),
            "serie": serie,
            "abiertas_total": len(aperturas),
            "resueltas": len(resoluciones),
            "n_ventanas": len(serie),
        }
        if serie
        else _nulo("sin ventanas evaluadas", n_ventanas=0)
    )
    # G7 adicional: tiempo de deteccion = apertura de la alerta - captura del primer frame
    # que cumple la condicion (inicio_condicion), en s.
    m["G7x_tiempo_deteccion_s"] = {
        a["alert_id"]: {
            "rule_id": a["rule_id"],
            "valor": ts(a["timestamp"]) - ts(a["inicio_condicion"]),
            "inicio_condicion": a["inicio_condicion"],
            "apertura": a["timestamp"],
        }
        for a in aperturas
        if a.get("inicio_condicion")
    }

    ventanas_suf = [v for v in ventanas if v["estado"] == "suficiente"]
    resumen = {
        "run_id": run["run_id"],
        "frames": n,
        "zonas": m["G4_zonas"],
        "ventanas": len(ventanas),
        "ventanas_suficientes": len(ventanas_suf),
        "ventanas_insuficientes": len(ventanas) - len(ventanas_suf),
        "alertas": [f"{a['alert_id']} {a['rule_id']}" for a in aperturas],
        "p_baja": m["G4_p_baja"].get("valor"),
        "inferencia_p95_ms": (m["G1_tiempo_inferencia_ms"].get("p95")),
        "fps_procesamiento": m["G2_fps_procesamiento"].get("valor"),
        "imagenes_vinculadas": m["G5_imagenes_vinculadas"].get("valor"),
    }
    return {
        "run_id": run["run_id"],
        "calculado_desde": [
            "run.json",
            "eventos.jsonl",
            "ventanas.jsonl",
            "alertas.jsonl",
            "capturas.jsonl",
            "config/",
        ],
        "metodo_percentil": "nearest-rank",
        "resumen": resumen,
        "metricas": m,
    }


def escribir(dir_run: Path) -> dict[str, Any]:
    datos = calcular(dir_run)
    (dir_run / "metricas.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return datos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recalcula metricas.json de una corrida")
    ap.add_argument("corrida", type=Path)
    args = ap.parse_args(argv)
    print(json.dumps(escribir(args.corrida)["resumen"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
