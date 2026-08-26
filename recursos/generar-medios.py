#!/usr/bin/env python3
"""
generar-medios.py — convierte una sesión de terminal escrita como guion en GIF y MP4.

POR QUÉ NO SE GRABA LA PANTALLA
    Una captura de pantalla real trae el ancho de la ventana de quien grabó, su tema, su prompt
    con el nombre de la máquina y, en un repo público, rutas que identifican a una persona. Y no
    se puede corregir: si el comando cambia, hay que volver a grabar todo.

    Acá la sesión es un archivo de texto (comandos + salida real capturada), y el video se
    renderiza. Eso da tres cosas: se regenera idéntico cuando cambia la herramienta, se anonimiza
    editando texto, y sale en los tres formatos que hacen falta sin volver a grabar.

FORMATOS QUE PRODUCE
    <nombre>.gif        para el README de GitHub (loop, paleta optimizada)
    <nombre>.mp4        16:9, para LinkedIn y para adjuntar
    <nombre>-vert.mp4   9:16 1080x1920, para Instagram y otras historias

USO
    python3 generar-medios.py guion.txt --salida ../media/optimizar-disco

FORMATO DEL GUION
    Líneas que empiezan con `$ ` son comandos: se "tipean" carácter a carácter.
    Las demás son salida: aparecen de golpe, como salen en una terminal real.
    `#pausa N` espera N décimas de segundo. `#limpiar` borra la pantalla.

REQUISITOS
    Python 3.8+ con Pillow, y ffmpeg en el PATH.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Falta Pillow: pip3 install Pillow")

# Paleta: fondo oscuro sobrio, legible en el tema claro y oscuro de GitHub por igual.
FONDO      = (22, 27, 34)
BARRA      = (33, 38, 45)
TEXTO      = (201, 209, 217)
PROMPT     = (126, 231, 135)
COMANDO    = (255, 255, 255)
ATENUADO   = (110, 118, 129)
ACENTO     = (121, 192, 255)
ALERTA     = (255, 166, 87)
OK         = (126, 231, 135)
CIRCULOS   = [(255, 95, 86), (255, 189, 46), (39, 201, 63)]

FUENTES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def cargar_fuente(tam):
    for f in FUENTES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, tam)
            except Exception:
                continue
    return ImageFont.load_default()


def color_de(linea):
    """Colorea por contenido, no por sintaxis: resalta lo que el ojo debe encontrar primero."""
    l = linea.strip()
    if l.startswith("==="):        return ACENTO
    if l.startswith(">>>"):        return ALERTA
    if "  ok " in linea or l.startswith("ok"):   return OK
    if l.startswith(("EXCLUIDO", "PROTEGIDO", "AVISOS")): return ALERTA
    if l.startswith(("#", "//")):  return ATENUADO
    return TEXTO


class Lienzo:
    def __init__(self, cols, filas, tam_fuente, titulo):
        self.fuente = cargar_fuente(tam_fuente)
        caja = self.fuente.getbbox("M")
        self.cw = caja[2] - caja[0]
        self.ch = int((caja[3] - caja[1]) * 1.9)
        self.margen = tam_fuente
        self.alto_barra = int(tam_fuente * 2.2)
        self.ancho = cols * self.cw + self.margen * 2
        self.alto = filas * self.ch + self.margen * 2 + self.alto_barra
        # dimensiones pares: libx264 con yuv420p las exige
        self.ancho += self.ancho % 2
        self.alto += self.alto % 2
        self.titulo = titulo
        self.filas = filas

    def render(self, lineas, cursor=False):
        img = Image.new("RGB", (self.ancho, self.alto), FONDO)
        d = ImageDraw.Draw(img)
        # barra de título: da contexto de "esto es una terminal" sin capturar una real
        d.rectangle([0, 0, self.ancho, self.alto_barra], fill=BARRA)
        r = self.alto_barra // 6
        for i, c in enumerate(CIRCULOS):
            cx = self.margen + i * (r * 3)
            cy = self.alto_barra // 2
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        tb = d.textbbox((0, 0), self.titulo, font=self.fuente)
        d.text(((self.ancho - tb[2]) / 2, (self.alto_barra - tb[3]) / 2 - 2),
               self.titulo, font=self.fuente, fill=ATENUADO)

        y = self.alto_barra + self.margen
        for ln in lineas[-self.filas:]:
            x = self.margen
            if ln.startswith("$ "):
                d.text((x, y), "$", font=self.fuente, fill=PROMPT)
                d.text((x + self.cw * 2, y), ln[2:], font=self.fuente, fill=COMANDO)
            else:
                d.text((x, y), ln, font=self.fuente, fill=color_de(ln))
            y += self.ch
        if cursor and lineas:
            ult = lineas[-1]
            x = self.margen + len(ult) * self.cw
            yy = self.alto_barra + self.margen + (min(len(lineas), self.filas) - 1) * self.ch
            d.rectangle([x, yy, x + self.cw, yy + self.ch - 4], fill=TEXTO)
        return img


def leer_guion(ruta, cols):
    """Devuelve una lista de (tipo, contenido). Recorta líneas largas al ancho del lienzo."""
    pasos = []
    for cruda in Path(ruta).read_text().splitlines():
        if cruda.startswith("#pausa"):
            pasos.append(("pausa", int(cruda.split()[1]))); continue
        if cruda.startswith("#limpiar"):
            pasos.append(("limpiar", 0)); continue
        if cruda.startswith("$ "):
            pasos.append(("comando", cruda)); continue
        pasos.append(("salida", cruda[:cols]))
    return pasos


def alto_necesario(pasos):
    """Máximo de líneas simultáneas en pantalla, simulando el guion sin renderizar."""
    n = maximo = 0
    for tipo, _ in pasos:
        if tipo == "limpiar":
            n = 0
        elif tipo in ("comando", "salida"):
            n += 1
            maximo = max(maximo, n)
    return maximo


def construir_frames(pasos, lienzo, dir_frames, fps):
    pantalla, n = [], 0

    def guardar(img, veces=1):
        nonlocal n
        for _ in range(veces):
            img.save(dir_frames / f"f{n:05d}.png"); n += 1

    guardar(lienzo.render([], cursor=True), fps // 2)
    for tipo, cont in pasos:
        if tipo == "limpiar":
            pantalla = []; guardar(lienzo.render(pantalla, cursor=True), max(2, fps // 4)); continue
        if tipo == "pausa":
            guardar(lienzo.render(pantalla, cursor=True), max(1, int(fps * cont / 10))); continue
        if tipo == "comando":
            # tipeo carácter a carácter: es lo que hace que se lea como una sesión y no como
            # una captura de pantalla con texto
            pantalla.append("$ ")
            for ch in cont[2:]:
                pantalla[-1] += ch
                guardar(lienzo.render(pantalla, cursor=True))
            guardar(lienzo.render(pantalla, cursor=True), max(2, fps // 3))
        else:
            pantalla.append(cont)
            guardar(lienzo.render(pantalla), 1)
    guardar(lienzo.render(pantalla), fps * 2)   # cola para leer el final antes del loop
    return n


def ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg falló:\n{r.stderr[:600]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("guion")
    ap.add_argument("--salida", required=True, help="ruta base, sin extensión")
    ap.add_argument("--cols", type=int, default=98)
    ap.add_argument("--filas", type=int, default=0,
                    help="alto en filas; 0 = calcularlo del guion (default)")
    ap.add_argument("--fuente", type=int, default=17)
    ap.add_argument("--fps", type=int, default=18)
    ap.add_argument("--titulo", default="")
    ap.add_argument("--sin-vertical", action="store_true")
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg")

    base = Path(a.salida); base.parent.mkdir(parents=True, exist_ok=True)
    pasos = leer_guion(a.guion, a.cols)
    # Alto automático: un lienzo fijo deja media pantalla en negro cuando el guion limpia y
    # vuelve a escribir poco. Se simula el guion para saber cuántas líneas llega a mostrar.
    filas = a.filas or max(3, alto_necesario(pasos))
    lienzo = Lienzo(a.cols, filas, a.fuente, a.titulo or base.name)
    print(f"alto calculado: {filas} filas")

    tmp = base.parent / f".frames-{base.name}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    print(f"lienzo {lienzo.ancho}x{lienzo.alto}, renderizando frames...")
    n = construir_frames(pasos, lienzo, tmp, a.fps)
    print(f"{n} frames")

    entrada = ["-framerate", str(a.fps), "-i", str(tmp / "f%05d.png")]

    # GIF con paleta propia: sin esto el degradado del fondo se ve sucio
    paleta = tmp / "paleta.png"
    ffmpeg(entrada + ["-vf", "palettegen=stats_mode=diff", str(paleta)])
    ffmpeg(entrada + ["-i", str(paleta),
                      "-lavfi", "paletteuse=dither=bayer:bayer_scale=3", str(base) + ".gif"])
    print(f"  {base}.gif")

    ffmpeg(entrada + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                      "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(base) + ".mp4"])
    print(f"  {base}.mp4")

    if not a.sin_vertical:
        # 9:16 para historias: la terminal centrada sobre fondo del mismo tono, sin recortar texto
        vf = ("scale=1000:-2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:"
              f"color=0x{FONDO[0]:02x}{FONDO[1]:02x}{FONDO[2]:02x}")
        ffmpeg(entrada + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                          "-vf", vf, str(base) + "-vert.mp4"])
        print(f"  {base}-vert.mp4")

    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
