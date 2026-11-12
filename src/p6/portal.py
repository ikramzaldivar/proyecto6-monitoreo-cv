"""Portal del centro de monitoreo (Flask).

    python -m p6.portal                 # http://127.0.0.1:8000

Al arrancar reconstruye `evidencias/portal.sqlite` desde `evidencias/corridas/*/` y
`evidencias/revisiones.jsonl`. Vistas obligatorias: eventos y alertas (con detalle y
vinculos a ventana, capturas, configuracion y registros). Vistas adicionales: tablero con
graficas por corrida, revision manual de capturas y exportacion CSV de eventos filtrados.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import threading
from pathlib import Path
from typing import Any

import yaml
from flask import Flask, Response, abort, redirect, render_template, request, send_file, url_for

from p6 import almacen
from p6.fuente import RAIZ, utc_iso

POR_PAGINA = 50
VEREDICTOS = ("baja_confirmada", "falsa_alarma", "requiere_seguimiento")
ZONA_COLOR = {"aceptada": "#2f7d4f", "duda": "#c58a00", "baja": "#c0392b"}

FILTROS_EVENTOS = {
    "run": "e.run_id = ?",
    "zona": "e.zona = ?",
    "status": "e.status = ?",
    "resultado": "e.resultado = ?",
    "clase": "e.event_id IN (SELECT event_id FROM detecciones WHERE clase = ?)",
    "secuencia": "e.sequence_id = ?",
    "ventana": "e.ventana_id = ?",
}


def crear_app(corridas: Path, db: Path, revisiones: Path) -> Flask:
    app = Flask(__name__)
    estado: dict[str, Any] = {}
    lock = threading.Lock()

    def recargar() -> None:
        with lock:
            estado["con"] = almacen.reconstruir(corridas, db, revisiones)

    def q(sql: str, args: tuple = ()) -> list[Any]:
        with lock:
            return estado["con"].execute(sql, args).fetchall()

    recargar()
    app.jinja_env.globals |= {"ZONA_COLOR": ZONA_COLOR, "json": json}

    @app.template_filter("pct")
    def pct(v: float | None) -> str:
        return "—" if v is None else f"{v * 100:.1f} %"

    @app.template_filter("num")
    def num(v: float | None, dec: int = 3) -> str:
        return "—" if v is None else f"{v:.{dec}f}"

    def corridas_lista() -> list[Any]:
        return q("SELECT run_id, escenario_id FROM corridas ORDER BY inicio")

    def filtros_eventos() -> tuple[str, tuple, dict[str, str]]:
        activos = {k: request.args[k] for k in FILTROS_EVENTOS if request.args.get(k)}
        where = [FILTROS_EVENTOS[k] for k in activos]
        args = list(activos.values())
        if request.args.get("capturado") == "1":
            where.append("e.imagen_ref IS NOT NULL")
            activos["capturado"] = "1"
        if (smax := request.args.get("score_max")) not in (None, ""):
            try:
                args.append(float(smax))
            except ValueError:
                abort(400, "score_max debe ser numerico")
            where.append("e.score < ?")
            activos["score_max"] = smax
        clausula = (" WHERE " + " AND ".join(where)) if where else ""
        return clausula, tuple(args), activos

    # ------------------------------------------------------------------ tablero
    @app.get("/")
    def tablero() -> str:
        filas = q("SELECT * FROM corridas ORDER BY inicio")
        runs = []
        for r in filas:
            met = json.loads(r["metricas_json"]) if r["metricas_json"] else None
            n_alertas = q("SELECT COUNT(*) n FROM alertas WHERE run_id=?", (r["run_id"],))[0]["n"]
            abiertas = q(
                "SELECT COUNT(*) n FROM alertas WHERE run_id=? AND estado='abierta'", (r["run_id"],)
            )[0]["n"]
            runs.append({"r": r, "met": met, "n_alertas": n_alertas, "abiertas": abiertas})
        sel = request.args.get("run") or (filas[-1]["run_id"] if filas else None)
        graficas = None
        if sel:
            if not q("SELECT 1 FROM corridas WHERE run_id=?", (sel,)):
                abort(404, f"corrida {sel} no existe")
            graficas = graficas_corrida(sel)
        ultimas = q("SELECT * FROM alertas ORDER BY abierta DESC LIMIT 5")
        return render_template("tablero.html", runs=runs, sel=sel, g=graficas, ultimas=ultimas)

    def graficas_corrida(run_id: str) -> dict[str, Any]:
        run = json.loads(q("SELECT run_json FROM corridas WHERE run_id=?", (run_id,))[0][0])
        ev = q(
            "SELECT seq, score, zona, status, resultado, event_id FROM eventos WHERE run_id=? ORDER BY seq",
            (run_id,),
        )
        ve = q("SELECT * FROM ventanas WHERE run_id=? ORDER BY indice", (run_id,))
        al = q("SELECT * FROM alertas WHERE run_id=? ORDER BY abierta", (run_id,))
        pol = run["politica"]
        ref = (run.get("referencia") or {}).get("p_baja")
        tol = minimo = None
        cfg = corridas / run_id / "config" / "monitoreo.yaml"
        if cfg.is_file():
            datos = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            tol = datos["reglas"]["cambio_sostenido"]["tolerancia"]
            minimo = datos["ventanas"]["minimo_puntuados"]
        return {
            "run": run,
            "scores": svg_scores(ev, pol["umbral_inferior"], pol["umbral_superior"], pol["piso_salida"]),
            "ventanas": svg_ventanas(ve, ref, tol),
            "activas": svg_activas(ve),
            "minimo": minimo,
            "alertas": al,
            "met": json.loads(
                q("SELECT metricas_json FROM corridas WHERE run_id=?", (run_id,))[0][0] or "null"
            ),
        }

    # ------------------------------------------------------------------ eventos
    @app.get("/eventos")
    def eventos() -> str:
        clausula, args, activos = filtros_eventos()
        try:
            pagina = max(1, int(request.args.get("pagina", 1)))
        except ValueError:
            abort(400, "pagina debe ser entero")
        total = q(f"SELECT COUNT(*) n FROM eventos e{clausula}", args)[0]["n"]
        filas = q(
            f"SELECT e.*, (SELECT COUNT(*) FROM alerta_evento ae WHERE ae.event_id=e.event_id) n_alertas "
            f"FROM eventos e{clausula} ORDER BY e.timestamp DESC, e.seq DESC LIMIT ? OFFSET ?",
            (*args, POR_PAGINA, (pagina - 1) * POR_PAGINA),
        )
        clases = [r[0] for r in q("SELECT DISTINCT clase FROM detecciones ORDER BY clase")]
        secuencias = [r[0] for r in q("SELECT DISTINCT sequence_id FROM eventos ORDER BY 1")]
        return render_template(
            "eventos.html",
            filas=filas,
            total=total,
            pagina=pagina,
            paginas=max(1, -(-total // POR_PAGINA)),
            activos=activos,
            corridas=corridas_lista(),
            clases=clases,
            secuencias=secuencias,
        )

    @app.get("/eventos/<event_id>")
    def evento(event_id: str) -> str:
        fila = q("SELECT * FROM eventos WHERE event_id=?", (event_id,))
        if not fila:
            abort(404, f"evento {event_id} no existe")
        e = json.loads(fila[0]["json"])
        alertas = q(
            "SELECT a.* FROM alertas a JOIN alerta_evento ae ON ae.alert_id=a.alert_id WHERE ae.event_id=?",
            (event_id,),
        )
        capturas = q("SELECT * FROM capturas WHERE event_id=?", (event_id,))
        revs = q("SELECT * FROM revisiones WHERE event_id=? ORDER BY timestamp", (event_id,))
        vecinos = q(
            "SELECT event_id, seq FROM eventos WHERE run_id=? AND seq IN (?, ?) ORDER BY seq",
            (e["run_id"], e["seq"] - 1, e["seq"] + 1),
        )
        return render_template(
            "evento.html", e=e, alertas=alertas, capturas=capturas, revs=revs, vecinos=vecinos
        )

    @app.get("/export/eventos.csv")
    def exportar() -> Response:
        clausula, args, _ = filtros_eventos()
        filas = q(f"SELECT * FROM eventos e{clausula} ORDER BY e.run_id, e.seq", args)
        cols = [
            "event_id",
            "run_id",
            "seq",
            "frame_id",
            "sequence_id",
            "source_id",
            "timestamp",
            "status",
            "resultado",
            "score",
            "zona",
            "clase_top",
            "n_detecciones",
            "ventana_id",
            "imagen_ref",
            "motivo_captura",
            "modelo",
            "config_ref",
            "error",
        ]
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(cols)
        for f in filas:
            w.writerow([f[c] for c in cols])
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=eventos.csv"},
        )

    # ------------------------------------------------------------------ alertas
    @app.get("/alertas")
    def alertas() -> str:
        filtros = {
            "run": "run_id = ?",
            "regla": "rule_id = ?",
            "severidad": "severidad = ?",
            "estado": "estado = ?",
        }
        activos = {k: request.args[k] for k in filtros if request.args.get(k)}
        clausula = (" WHERE " + " AND ".join(filtros[k] for k in activos)) if activos else ""
        filas = q(f"SELECT * FROM alertas{clausula} ORDER BY abierta DESC", tuple(activos.values()))
        reglas = [r[0] for r in q("SELECT DISTINCT rule_id FROM alertas ORDER BY 1")]
        return render_template(
            "alertas.html", filas=filas, activos=activos, corridas=corridas_lista(), reglas=reglas
        )

    @app.get("/alertas/<alert_id>")
    def alerta(alert_id: str) -> str:
        fila = q("SELECT * FROM alertas WHERE alert_id=?", (alert_id,))
        if not fila:
            abort(404, f"alerta {alert_id} no existe")
        a = fila[0]
        eventos_ = q(
            "SELECT e.* FROM eventos e JOIN alerta_evento ae ON ae.event_id=e.event_id "
            "WHERE ae.alert_id=? ORDER BY e.seq",
            (alert_id,),
        )
        ventanas_ = q(
            "SELECT v.* FROM ventanas v JOIN alerta_ventana av ON av.ventana_id=v.ventana_id "
            "WHERE av.alert_id=? ORDER BY v.indice",
            (alert_id,),
        )
        return render_template(
            "alerta.html",
            a=a,
            ap=json.loads(a["json"]),
            registros=json.loads(a["registros"]),
            eventos=eventos_,
            ventanas=[json.loads(v["json"]) for v in ventanas_],
        )

    # ------------------------------------------------------------------ ventanas y corridas
    @app.get("/ventanas/<ventana_id>")
    def ventana(ventana_id: str) -> str:
        fila = q("SELECT * FROM ventanas WHERE ventana_id=?", (ventana_id,))
        if not fila:
            abort(404, f"ventana {ventana_id} no existe")
        v = json.loads(fila[0]["json"])
        ev = q("SELECT * FROM eventos WHERE ventana_id=? ORDER BY seq", (ventana_id,))
        al = q(
            "SELECT a.* FROM alertas a JOIN alerta_ventana av ON av.alert_id=a.alert_id WHERE av.ventana_id=?",
            (ventana_id,),
        )
        return render_template("ventana.html", v=v, eventos=ev, alertas=al)

    @app.get("/corridas/<run_id>")
    def corrida(run_id: str) -> str:
        fila = q("SELECT * FROM corridas WHERE run_id=?", (run_id,))
        if not fila:
            abort(404, f"corrida {run_id} no existe")
        base = corridas / run_id / "config"
        archivos = (
            {p.name: p.read_text(encoding="utf-8") for p in sorted(base.iterdir())} if base.is_dir() else {}
        )
        return render_template(
            "corrida.html",
            run=json.loads(fila[0]["run_json"]),
            met=json.loads(fila[0]["metricas_json"] or "null"),
            archivos=archivos,
        )

    @app.get("/corridas/<run_id>/archivo/<nombre>")
    def archivo(run_id: str, nombre: str) -> Response:
        permitidos = {
            "eventos.jsonl",
            "ventanas.jsonl",
            "alertas.jsonl",
            "capturas.jsonl",
            "run.json",
            "metricas.json",
        }
        ruta = corridas / run_id / nombre
        if nombre not in permitidos or not ruta.is_file():
            abort(404)
        return send_file(ruta, mimetype="text/plain")

    @app.get("/imagenes/<run_id>/<path:ref>")
    def imagen(run_id: str, ref: str) -> Response:
        base = (corridas / run_id).resolve()
        ruta = (base / ref).resolve()
        if base not in ruta.parents or not ruta.is_file():
            abort(404, "imagen no encontrada")
        return send_file(ruta)

    # ------------------------------------------------------------------ revision de capturas
    @app.get("/capturas")
    def capturas() -> str:
        filtros = {"run": "c.run_id = ?", "motivo": "c.motivo = ?", "zona": "e.zona = ?"}
        activos = {k: request.args[k] for k in filtros if request.args.get(k)}
        where = [filtros[k] for k in activos]
        rev = request.args.get("revision")
        if rev == "pendiente":
            where.append("r.veredicto IS NULL")
        elif rev in VEREDICTOS:
            where.append("r.veredicto = ?")
        clausula = (" WHERE " + " AND ".join(where)) if where else ""
        args = tuple(activos.values()) + ((rev,) if rev in VEREDICTOS else ())
        if rev:
            activos["revision"] = rev
        filas = q(
            "SELECT c.*, e.score, e.zona, e.status, e.clase_top, e.seq, r.veredicto, r.nota, r.timestamp rev_ts "
            "FROM capturas c JOIN eventos e ON e.event_id=c.event_id "
            "LEFT JOIN (SELECT * FROM revisiones WHERE rowid IN "
            "  (SELECT MAX(rowid) FROM revisiones GROUP BY capture_id)) r ON r.capture_id=c.capture_id"
            f"{clausula} ORDER BY c.run_id, e.seq LIMIT 200",
            args,
        )
        motivos = [r[0] for r in q("SELECT DISTINCT motivo FROM capturas ORDER BY 1")]
        return render_template(
            "capturas.html",
            filas=filas,
            activos=activos,
            corridas=corridas_lista(),
            motivos=motivos,
            veredictos=VEREDICTOS,
        )

    @app.post("/capturas/<capture_id>/revision")
    def revisar(capture_id: str) -> Response:
        fila = q("SELECT * FROM capturas WHERE capture_id=?", (capture_id,))
        if not fila:
            abort(404, f"captura {capture_id} no existe")
        veredicto = request.form.get("veredicto", "")
        nota = request.form.get("nota", "").strip()[:500]
        if veredicto not in VEREDICTOS:
            abort(400, f"veredicto debe ser uno de {VEREDICTOS}")
        ahora = utc_iso()
        registro = {
            "revision_id": f"{capture_id}-r{ahora}",
            "capture_id": capture_id,
            "event_id": fila[0]["event_id"],
            "timestamp": ahora,
            "veredicto": veredicto,
            "nota": nota,
        }
        with lock:
            with revisiones.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(registro, ensure_ascii=False) + "\n")
            almacen.guardar_revision(estado["con"], registro)
            estado["con"].commit()
        destino = request.form.get("volver") or url_for("capturas")
        return redirect(destino if destino.startswith("/") else url_for("capturas"))

    @app.post("/recargar")
    def recargar_post() -> Response:
        recargar()
        return redirect(url_for("tablero"))

    @app.errorhandler(400)
    @app.errorhandler(404)
    def error(e: Any) -> tuple[str, int]:
        return render_template("error.html", e=e), e.code

    return app


# ---------------------------------------------------------------------- graficas SVG
ANCHO, ALTO, M = 860, 220, 36


def _x(i: int, n: int) -> float:
    return M + (ANCHO - 2 * M) * (i / max(1, n - 1))


def _y(v: float) -> float:
    return ALTO - M + (-(ALTO - 2 * M)) * v


def _ejes(titulo_y: str) -> list[str]:
    partes = [f'<line x1="{M}" y1="{_y(0)}" x2="{ANCHO - M}" y2="{_y(0)}" class="eje"/>']
    for v in (0, 0.25, 0.5, 0.75, 1.0):
        partes.append(f'<text x="{M - 6}" y="{_y(v) + 4}" class="tick" text-anchor="end">{v:.2f}</text>')
        partes.append(f'<line x1="{M}" y1="{_y(v)}" x2="{ANCHO - M}" y2="{_y(v)}" class="grid"/>')
    partes.append(f'<text x="8" y="{M - 14}" class="tick">{titulo_y}</text>')
    return partes


def _umbral(v: float, etiqueta: str, clase: str) -> str:
    return (
        f'<line x1="{M}" y1="{_y(v):.1f}" x2="{ANCHO - M}" y2="{_y(v):.1f}" class="{clase}"/>'
        f'<text x="{ANCHO - M - 2}" y="{_y(v) - 3:.1f}" class="tick" text-anchor="end">{etiqueta}</text>'
    )


def svg_scores(eventos: list[Any], inf: float, sup: float, piso: float) -> str:
    n = len(eventos)
    if n == 0:
        return '<p class="vacio">La corrida no tiene eventos.</p>'
    partes = _ejes("score del frame")
    partes += [
        _umbral(sup, f"sup {sup}", "umbral"),
        _umbral(inf, f"inf {inf}", "umbral"),
        _umbral(piso, f"piso {piso}", "piso"),
    ]
    for i, e in enumerate(eventos):
        x = _x(i, n)
        url = f"/eventos/{e['event_id']}"
        if e["status"] == "error":
            partes.append(
                f'<a href="{url}"><text x="{x:.1f}" y="{_y(0) - 4:.1f}" class="marca-error" text-anchor="middle">✕<title>#{e["seq"]} error</title></text></a>'
            )
        elif e["score"] is None:
            partes.append(
                f'<a href="{url}"><rect x="{x - 3:.1f}" y="{_y(0) - 3:.1f}" width="6" height="6" class="marca-sin"><title>#{e["seq"]} sin detecciones</title></rect></a>'
            )
        else:
            partes.append(
                f'<a href="{url}"><circle cx="{x:.1f}" cy="{_y(e["score"]):.1f}" r="4" fill="{ZONA_COLOR[e["zona"]]}">'
                f"<title>#{e['seq']} s={e['score']:.3f} {e['zona']}</title></circle></a>"
            )
    return f'<svg viewBox="0 0 {ANCHO} {ALTO}" class="grafica" role="img" aria-label="Puntuacion por frame">{"".join(partes)}</svg>'


def svg_ventanas(ventanas: list[Any], ref: float | None, tol: float | None) -> str:
    n = len(ventanas)
    if n == 0:
        return '<p class="vacio">Sin ventanas evaluadas.</p>'
    partes = _ejes("p_baja por ventana")
    ancho = (ANCHO - 2 * M) / n
    for i, v in enumerate(ventanas):
        x = M + i * ancho
        url = f"/ventanas/{v['ventana_id']}"
        if v["p_baja"] is None:
            partes.append(
                f'<a href="{url}"><rect x="{x + 2:.1f}" y="{_y(1):.1f}" width="{ancho - 4:.1f}" height="{_y(0) - _y(1):.1f}" class="insuf"><title>v{v["indice"]}: evidencia insuficiente</title></rect></a>'
            )
        else:
            clase = "barra-alerta" if v["n_alertas_activas"] else "barra"
            partes.append(
                f'<a href="{url}"><rect x="{x + 2:.1f}" y="{_y(v["p_baja"]):.1f}" width="{ancho - 4:.1f}" height="{max(1, _y(0) - _y(v["p_baja"])):.1f}" class="{clase}"><title>v{v["indice"]}: p_baja={v["p_baja"]:.2f}</title></rect></a>'
            )
        partes.append(
            f'<text x="{x + ancho / 2:.1f}" y="{ALTO - M + 14}" class="tick" text-anchor="middle">v{v["indice"]}</text>'
        )
    partes.append(_umbral(0.5, "regla 0.50", "umbral"))
    if ref is not None:
        partes.append(_umbral(ref, f"ref {ref:.2f}", "piso"))
        if tol is not None:
            partes.append(_umbral(ref + tol, f"ref+tol {ref + tol:.2f}", "umbral-sost"))
    return f'<svg viewBox="0 0 {ANCHO} {ALTO}" class="grafica" role="img" aria-label="p_baja por ventana">{"".join(partes)}</svg>'


def svg_activas(ventanas: list[Any]) -> str:
    n = len(ventanas)
    if n == 0:
        return '<p class="vacio">Sin ventanas evaluadas.</p>'
    maximo = max(1, max(v["n_alertas_activas"] for v in ventanas))
    alto = 120
    puntos = []
    for i, v in enumerate(ventanas):
        x = _x(i, n)
        y = alto - 24 - (alto - 48) * v["n_alertas_activas"] / maximo
        puntos.append(f"{x:.1f},{y:.1f}")
    partes = [
        f'<polyline points="{" ".join(puntos)}" class="linea"/>',
        f'<line x1="{M}" y1="{alto - 24}" x2="{ANCHO - M}" y2="{alto - 24}" class="eje"/>',
        f'<text x="8" y="14" class="tick">alertas activas al cerrar cada ventana (max {maximo})</text>',
    ]
    for i, v in enumerate(ventanas):
        partes.append(
            f'<text x="{_x(i, n):.1f}" y="{alto - 8}" class="tick" text-anchor="middle">{v["n_alertas_activas"]}</text>'
        )
    return f'<svg viewBox="0 0 {ANCHO} {alto}" class="grafica" role="img" aria-label="Alertas activas">{"".join(partes)}</svg>'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Portal del centro de monitoreo")
    ap.add_argument("--corridas", type=Path, default=RAIZ / "evidencias" / "corridas")
    ap.add_argument("--db", type=Path, default=RAIZ / "evidencias" / "portal.sqlite")
    ap.add_argument("--revisiones", type=Path, default=RAIZ / "evidencias" / "revisiones.jsonl")
    ap.add_argument("--puerto", type=int, default=8000)
    args = ap.parse_args(argv)
    app = crear_app(args.corridas.resolve(), args.db.resolve(), args.revisiones.resolve())
    app.run(host="127.0.0.1", port=args.puerto, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
