"""Prepara las secuencias derivadas de las capturas originales del carrito.

    python scripts/preparar_secuencias.py

Cambia solo la IMAGEN de entrada (iluminacion, enfoque o bytes del archivo); las
puntuaciones salen despues del modelo real. Cada salida tiene su propio `capturas.csv` con
el frame y SHA-256 de origen y la transformacion aplicada. Es determinista para una misma
version de Pillow (la version usada queda en el manifiesto).

- poca-luz/     S5 con desenfoque gaussiano radio 3 y brillo x0.30 (C2).
- desenfoque/   S5 y S2 con desenfoque gaussiano radio 7: camara fuera de foco (extra E1).
- corruptas/    4 frames de S5 truncados al 30 % de sus bytes y 1 archivo vacio (extra E2).
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable
from pathlib import Path

import PIL
from PIL import Image, ImageEnhance, ImageFilter

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = RAIZ / "datos" / "carrito"
DESTINO = RAIZ / "datos" / "preparadas"
CAMPOS = [
    "sequence_id",
    "frame_id",
    "path",
    "sha256",
    "origen_path",
    "origen_sha256",
    "transformacion",
    "pillow",
]


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def filas(secuencias: list[str]) -> list[dict[str, str]]:
    with (ORIGEN / "capturas.csv").open(encoding="utf-8", newline="") as f:
        todas = list(csv.DictReader(f))
    return [r for s in secuencias for r in todas if r["sequence_id"] == s]


def escribir(nombre: str, registros: list[dict[str, str]]) -> None:
    with (DESTINO / nombre / "capturas.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CAMPOS, lineterminator="\n")
        w.writeheader()
        w.writerows(registros)
    print(f"{nombre}: {len(registros)} frames")


def imagen(nombre: str, secuencias: list[str], sufijo: str, desc: str, f: Callable) -> None:
    carpeta = DESTINO / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    registros = []
    for r in filas(secuencias):
        origen = ORIGEN / r["path"]
        if sha(origen) != r["sha256"]:
            raise SystemExit(f"{origen}: SHA-256 distinto del manifiesto")
        with Image.open(origen) as im:
            salida = f(im.convert("RGB"))
        ruta = carpeta / f"{r['sequence_id']}-{sufijo}_{r['frame_id']}.jpg"
        salida.save(ruta, format="JPEG", quality=90)
        registros.append(
            {
                "sequence_id": f"{r['sequence_id']}-{sufijo}",
                "frame_id": f"{r['frame_id']}-{sufijo}",
                "path": ruta.name,
                "sha256": sha(ruta),
                "origen_path": f"datos/carrito/{r['path']}",
                "origen_sha256": r["sha256"],
                "transformacion": desc,
                "pillow": PIL.__version__,
            }
        )
    escribir(nombre, registros)


def corruptas() -> None:
    carpeta = DESTINO / "corruptas"
    carpeta.mkdir(parents=True, exist_ok=True)
    registros = []
    for i, r in enumerate(filas(["S5"])[:5]):
        origen = ORIGEN / r["path"]
        datos = origen.read_bytes()
        vacio = i == 4
        recorte = b"" if vacio else datos[: int(len(datos) * 0.30)]
        ruta = carpeta / f"S5-corrupta_{r['frame_id']}.jpg"
        ruta.write_bytes(recorte)
        registros.append(
            {
                "sequence_id": "S5-corrupta",
                "frame_id": f"{r['frame_id']}-corrupta",
                "path": ruta.name,
                "sha256": sha(ruta),
                "origen_path": f"datos/carrito/{r['path']}",
                "origen_sha256": r["sha256"],
                "transformacion": "archivo vacio" if vacio else "truncado al 30% de los bytes",
                "pillow": PIL.__version__,
            }
        )
    escribir("corruptas", registros)


def main() -> int:
    imagen(
        "poca-luz",
        ["S5"],
        "poca-luz",
        "GaussianBlur(radio=3) y luego Brightness(0.30)",
        lambda im: ImageEnhance.Brightness(im.filter(ImageFilter.GaussianBlur(3))).enhance(0.30),
    )
    imagen(
        "desenfoque",
        ["S5", "S2"],
        "desenfoque",
        "GaussianBlur(radio=7)",
        lambda im: im.filter(ImageFilter.GaussianBlur(7)),
    )
    corruptas()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
