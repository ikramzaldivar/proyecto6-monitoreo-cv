"""Descarga los pesos del detector y valida su SHA-256 (reutilizado de P5, `modelo/descriptor.yaml`).

    python scripts/descargar_modelo.py --destino modelo/

Lee URL, bytes y SHA-256 del descriptor; descarga a un archivo temporal en `--destino`,
calcula el hash sobre los bytes recibidos y solo entonces lo renombra al nombre final.
Si el archivo ya existe con el hash correcto no vuelve a descargarlo; si existe con otro
hash, lo reemplaza. No usa credenciales, S3 ni enlaces temporales. Detras de un proxy
que intercepta TLS, apunta SSL_CERT_FILE (o REQUESTS_CA_BUNDLE) al PEM de su CA.

Codigos de salida: 0 pesos verificados; 1 el SHA-256 o el tamano no coinciden (no deja
archivo); 2 descriptor invalido o error de red/disco.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

import certifi
import yaml

DESCRIPTOR = Path(__file__).resolve().parents[1] / "modelo" / "descriptor.yaml"
BLOQUE = 1 << 20
USER_AGENT = "p6-descargar-modelo/1.0"


def contexto_tls() -> ssl.SSLContext:
    """Raices TLS: SSL_CERT_FILE o REQUESTS_CA_BUNDLE si existen (proxy corporativo con su
    propia CA); si no, las de certifi (version fijada), porque en Windows el almacen del
    sistema carga raices bajo demanda y Python fallaba ~1 de cada 2 veces contra GitHub."""
    cafile = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE") or certifi.where()
    try:
        return ssl.create_default_context(cafile=cafile)
    except OSError as e:  # PEM inexistente o ilegible: se dice cual
        raise OSError(f"no se pudieron cargar las raices TLS de {cafile}: {e}") from e


class HashNoCoincideError(Exception):
    """Los bytes descargados no son los declarados en el descriptor."""


def leer_descriptor(ruta: Path) -> dict[str, Any]:
    data = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    faltan = [c for c in ("archivo", "url", "bytes", "sha256") if c not in data]
    if faltan:
        raise ValueError(f"{ruta}: faltan campos {faltan}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data["sha256"])):
        raise ValueError(f"{ruta}: sha256 debe ser hex de 64 caracteres en minusculas")
    if Path(data["archivo"]).name != data["archivo"]:
        raise ValueError(f"{ruta}: archivo debe ser un nombre sin carpetas")
    return data


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(BLOQUE):
            h.update(bloque)
    return h.hexdigest()


def descargar(url: str, destino: Path, sha256: str, tamano: int) -> None:
    """Escribe `url` en `destino` solo si sus bytes tienen exactamente `sha256` y `tamano`."""
    tmp = destino.with_name(destino.name + ".parcial")
    h = hashlib.sha256()
    total = 0
    peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (
            urllib.request.urlopen(peticion, timeout=60, context=contexto_tls()) as resp,
            tmp.open("wb") as f,
        ):
            while bloque := resp.read(BLOQUE):
                h.update(bloque)
                total += len(bloque)
                f.write(bloque)
        obtenido = h.hexdigest()
        if obtenido != sha256 or total != tamano:
            raise HashNoCoincideError(
                f"esperado sha256={sha256} bytes={tamano}; obtenido sha256={obtenido} bytes={total}"
            )
        tmp.replace(destino)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destino", type=Path, required=True, help="carpeta para los pesos")
    parser.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    args = parser.parse_args(argv)

    try:
        d = leer_descriptor(args.descriptor)
        args.destino.mkdir(parents=True, exist_ok=True)
        archivo = args.destino / d["archivo"]
        if archivo.exists() and sha256_de(archivo) == d["sha256"]:
            print(f"ya presente: {archivo}")
        else:
            print(f"descargando {d['url']}")
            descargar(d["url"], archivo, d["sha256"], int(d["bytes"]))
        # se vuelve a leer del disco: el hash que se reporta es el del archivo final
        obtenido = sha256_de(archivo)
    except HashNoCoincideError as e:
        print(f"ERROR: SHA-256 no coincide, no se guardo el archivo: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if obtenido != d["sha256"]:
        print(f"ERROR: SHA-256 no coincide en {archivo}: {obtenido}", file=sys.stderr)
        return 1
    print(f"archivo: {archivo}")
    print(f"bytes:   {archivo.stat().st_size}")
    print(f"sha256:  {obtenido} (coincide con {args.descriptor.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
