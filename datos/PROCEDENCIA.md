# Procedencia de los datos visuales

## `carrito/` — capturas originales de la cámara del carrito (Proyecto 5)

- Copia sin cambios de `Proyecto5/datos/evaluacion/` del repositorio del equipo
  [sebastian0023/Proyecto-3-Clasificador-de-imagenes](https://github.com/sebastian0023/Proyecto-3-Clasificador-de-imagenes),
  commit `b63ddbc91a45db90d857c635def6a344ce895b09` (4 nov 2026).
- 78 frames JPEG 400×296 de seis secuencias (S1–S6), capturados con la ESP32-CAM del carrito
  por el equipo de P5 (captura: Bryan; selección y anotación: Emilio). `capturas.csv` es el
  manifiesto original con `frame_id`, `sha256`, escena y sesión.
- En P6 no se usan las anotaciones de P5: no se mide calidad predictiva.
- Cada evento guarda la ruta y el SHA-256 del manifiesto; la métrica de trazabilidad
  (G5x) comprueba que los bytes no cambiaron.

## `preparadas/` — secuencias derivadas (generadas por mí)

`python scripts/preparar_secuencias.py` las genera desde `carrito/`. Cada carpeta tiene su
`capturas.csv` con el frame y SHA-256 de origen, la transformación y la versión de Pillow.
Las transformaciones cambian la imagen de entrada; las puntuaciones salen después del
modelo real, nunca se escriben a mano.

| Carpeta | Origen | Transformación | Uso |
| --- | --- | --- | --- |
| `poca-luz/` | S5 (12) | `GaussianBlur(3)` y `Brightness(0.30)`: poca luz con desenfoque | C2 |
| `desenfoque/` | S5 y S2 (29) | `GaussianBlur(7)`: cámara fuera de foco | Extra E1 |
| `corruptas/` | S5 (5) | 4 JPEG truncados al 30 % de sus bytes y 1 archivo vacío | Extra E2 |
