#!/usr/bin/env python3
"""traer-de-youtube: trae de YouTube lo que sirve para trabajar, a disco local.

Subcomandos:

    transcribir URL [--salida DIR] [--idioma es] [--whisper]
        Escribe un .md con metadatos, descripción (suele traer links al repo y comandos),
        capítulos y la transcripción por párrafos con su minuto enlazado. Usa los subtítulos de
        YouTube (manuales antes que automáticos); si no hay, o con --whisper, transcribe en local
        con whisper.cpp. Imprime la ruta del .md.

    capturas URL (--en 1:20,3:45 | --cada SEG) [--salida DIR]
        Baja el video a 720p como máximo y extrae fotogramas en esos minutos: el código que se
        muestra en pantalla no está en la transcripción. Imprime una ruta de imagen por línea.

    info URL [URL ...]
        Título | duración | capítulos | subtítulos disponibles, sin bajar nada.

    destinos
        Unidades externas montadas: ruta<TAB>fs<TAB>bytes_libres.

    bajar CARPETA URL [URL ...]
        Baja cada link como MP3 a CARPETA y emite una línea TSV por link. Lo usa
        audio-a-pendrive.sh, que es quien copia al pendrive (ver COPIA).

Requiere yt-dlp y ffmpeg (y deno para los desafíos JS que hoy pone YouTube). La transcripción
local requiere whisper-cli (whisper.cpp) y un modelo ggml en ~/.cache/whisper-models o en
$WHISPER_MODELO. Solo biblioteca estándar.

LINKS. Se deja solo el video (`v=`): un link copiado desde una "Mix" trae `&list=RD...` y sin esto
se bajarían decenas de videos.

COPIA. Medido en macOS 27 sobre FAT32: todo archivo creado por un proceso que desciende de este
Python (shutil.copyfile, open/write, os.mkdir, e incluso un `cp -X` lanzado con subprocess) recibe
`com.apple.provenance`, y en FAT32 macOS lo guarda en un `._nombre` oculto que muchas radios
listan como pista rota. Desde bash, `cp -X` no lo deja. Por eso la copia al pendrive vive en el .sh.
"""

import argparse
import datetime as dt
import glob
import html
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import parse_qs, urlparse

LARGO_AVISO_SEG = 10 * 60   # sobre esto, un "audio" probablemente trae varias canciones
PARRAFO_SEG = 45            # largo de cada párrafo de la transcripción
MAX_NOMBRE = 120
MAX_CAPTURAS = 40           # cada imagen cuesta contexto al leerla

PROMO = re.compile(
    r"[\(\[]\s*("
    r"official\s+(music\s+)?video|official\s+(lyric\s+)?video|official\s+audio|music\s+video|"
    r"lyric\s+video|lyrics?|video\s*clip\s+oficial|video\s+oficial|audio\s+oficial|"
    r"con\s+letra|letra|hd|hq|4k|visualizer"
    r")\s*[\)\]]",
    re.IGNORECASE,
)
REEMPLAZOS = {
    "|": " - ", "｜": " - ", "/": " - ", "⧸": " - ", "\\": " - ", "＼": " - ",
    ":": " -", "：": " -", "?": "", "？": "", "*": "", "＊": "", '"': "", "＂": "",
    "“": "", "”": "", "<": "", ">": "", "＜": "", "＞": "", "\t": " ",
}


def correr(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def requiere(*herramientas):
    for h in herramientas:
        if not shutil.which(h):
            sys.exit(f"ERROR: falta {h} en el PATH")


# ================================================================= links, nombres, tiempos

def limpiar_url(url):
    """Deja solo el video: quita list=, index=, start_radio=, t= y el resto."""
    u = urlparse(url.strip())
    host = (u.hostname or "").lower()
    vid = ""
    if host.endswith("youtu.be"):
        vid = u.path.strip("/").split("/")[0]
    elif "youtube" in host:
        partes = u.path.split("/")
        if len(partes) > 2 and partes[1] in ("shorts", "live"):
            vid = partes[2]
        else:
            vid = parse_qs(u.query).get("v", [""])[0]
    return f"https://www.youtube.com/watch?v={vid}" if vid else url.strip()


def nombre_limpio(titulo, respaldo):
    t = unicodedata.normalize("NFC", titulo or "")
    t = t.replace("||", "|")
    for malo, bueno in REEMPLAZOS.items():
        t = t.replace(malo, bueno)
    t = PROMO.sub("", t)
    t = "".join(c for c in t if unicodedata.category(c) not in ("So", "Cs", "Cc", "Cf")
                and c not in "️‍")
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"\s*-\s*(-\s*)+", " - ", t)
    t = re.sub(r"\s+", " ", t).strip(" .-_")
    if len(t) > MAX_NOMBRE:
        t = t[:MAX_NOMBRE].rsplit(" ", 1)[0].strip(" .-_")
    return t or respaldo


def slug(texto, largo=60):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    return t[:largo].rstrip("-") or "video"


def mmss(seg):
    if seg is None:
        return "?"
    seg = int(seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def a_segundos(texto):
    """'1:20' -> 80, '1:02:03' -> 3723, '95' -> 95, '00:01:02.500' -> 62.5"""
    seg = 0.0
    for p in texto.strip().split(":"):
        seg = seg * 60 + float(p)
    return seg


# ================================================================= YouTube

def info_video(url):
    r = correr(["yt-dlp", "--no-playlist", "-J", url])
    if r.returncode != 0:
        raise RuntimeError(pista_error(r.stderr))
    return json.loads(r.stdout)


def pista_error(stderr):
    ultimas = " / ".join((stderr or "").strip().splitlines()[-3:])
    if re.search(r"Sign in|403|nsig|signature|challenge|Requested format", stderr or "", re.I):
        ultimas += " (pista: suele ser yt-dlp desactualizado; actualízalo y reintenta)"
    return ultimas or "yt-dlp falló sin mensaje"


def aviso_audio(info):
    caps = info.get("chapters") or []
    if caps:
        return f"trae {len(caps)} capítulos (se puede partir en pistas)"
    if (info.get("duration") or 0) > LARGO_AVISO_SEG:
        return "largo y sin capítulos: probablemente varias canciones en una pista"
    return ""


# ================================================================= transcripción

def elegir_subtitulos(info, idioma):
    """Devuelve (idioma, 'manual'|'auto') o (None, None). Manual antes que automático, y el
    idioma original antes que una traducción automática."""
    original = (info.get("language") or "").split("-")[0]
    manuales = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    autos = info.get("automatic_captions") or {}
    preferidos = [x for x in [idioma, original, "es", "en"] if x]
    for lang in preferidos:
        for clave in manuales:
            if clave == lang or clave.startswith(lang + "-"):
                return clave, "manual"
    for lang in preferidos:
        for clave in (f"{lang}-orig", lang):
            if clave in autos:
                return clave, "auto"
    return None, None


def bajar_vtt(url, lang, tipo, carpeta):
    flag = "--write-subs" if tipo == "manual" else "--write-auto-subs"
    r = correr(["yt-dlp", "--no-playlist", "--skip-download", flag, "--sub-langs", lang,
                "--sub-format", "vtt", "-o", os.path.join(carpeta, "subs.%(ext)s"), url])
    archivos = glob.glob(os.path.join(carpeta, "subs*.vtt"))
    if not archivos:
        raise RuntimeError(pista_error(r.stderr) if r.returncode else "yt-dlp no entregó el .vtt")
    return archivos[0]


def leer_vtt(ruta):
    """Lista de (segundo, línea) sin repeticiones. Los subtítulos automáticos de YouTube repiten
    cada línea en el cue siguiente (texto 'rodante'): se emite una línea solo si no es igual a la
    anterior emitida."""
    lineas, ultima, inicio = [], None, 0.0
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for crudo in f:
            l = crudo.strip()
            m = re.match(r"^(\d[\d:.]*)\s+-->\s+", l)
            if m:
                inicio = a_segundos(m.group(1))
                continue
            if not l or l.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE")):
                continue
            texto = html.unescape(re.sub(r"<[^>]+>", "", l)).strip()
            if texto and texto != ultima:
                lineas.append((inicio, texto))
                ultima = texto
    return lineas


def modelo_whisper():
    explicito = os.environ.get("WHISPER_MODELO")
    if explicito and os.path.isfile(explicito):
        return explicito
    carpeta = os.path.expanduser("~/.cache/whisper-models")
    candidatos = sorted(glob.glob(os.path.join(carpeta, "ggml-*turbo*.bin"))) \
        + sorted(glob.glob(os.path.join(carpeta, "ggml-*.bin")))
    return candidatos[0] if candidatos else None


def transcribir_local(url, info, idioma, carpeta):
    """Baja el audio y lo pasa por whisper.cpp. Devuelve lista de (segundo, texto)."""
    requiere("whisper-cli", "ffmpeg")
    modelo = modelo_whisper()
    if not modelo:
        sys.exit("ERROR: no hay modelo de whisper. Descarga uno, por ejemplo:\n"
                 "  mkdir -p ~/.cache/whisper-models && curl -L -o "
                 "~/.cache/whisper-models/ggml-large-v3-turbo-q5_0.bin "
                 "'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
                 "ggml-large-v3-turbo-q5_0.bin?download=true'")
    r = correr(["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-o",
                os.path.join(carpeta, "audio.%(ext)s"), url])
    audios = [a for a in glob.glob(os.path.join(carpeta, "audio.*")) if not a.endswith(".part")]
    if not audios:
        raise RuntimeError(pista_error(r.stderr))
    wav = os.path.join(carpeta, "audio.wav")
    r = correr(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", audios[0],
                "-ar", "16000", "-ac", "1", wav])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg: {r.stderr.strip()[:200]}")
    # whisper inventa frases plausibles sobre el silencio: un video mudo no se transcribe
    v = correr(["ffmpeg", "-nostdin", "-i", wav, "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", v.stderr)
    if m and float(m.group(1)) < -45:
        return []
    lang = idioma or (info.get("language") or "auto").split("-")[0]
    r = correr(["whisper-cli", "-m", modelo, "-f", wav, "-l", lang, "--no-prints"])
    if r.returncode != 0:
        raise RuntimeError(f"whisper: {(r.stderr or r.stdout).strip()[:200]}")
    lineas = []
    for l in r.stdout.splitlines():
        m = re.match(r"^\[(\d[\d:.]*)\s+-->\s+[\d:.]+\]\s*(.*)$", l.strip())
        if m and m.group(2).strip():
            lineas.append((a_segundos(m.group(1)), m.group(2).strip()))
    return lineas


def parrafos(lineas, capitulos):
    """Agrupa líneas en párrafos de ~PARRAFO_SEG, cortando también en cada capítulo."""
    cortes = sorted(c.get("start_time", 0) for c in capitulos)

    def capitulo_de(s):
        return sum(1 for c in cortes if c <= s)

    salida, actual, inicio = [], [], None
    for seg, texto in lineas:
        if actual and (seg - inicio >= PARRAFO_SEG or capitulo_de(seg) != capitulo_de(inicio)):
            salida.append((inicio, " ".join(actual)))
            actual = []
        if not actual:
            inicio = seg
        actual.append(texto)
    if actual:
        salida.append((inicio, " ".join(actual)))
    return salida


def armar_md(info, url, fuente, lang, lineas, modelo=None):
    vid = info.get("id", "")
    caps = info.get("chapters") or []
    fecha = info.get("upload_date") or ""
    fecha = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}" if len(fecha) == 8 else "?"
    canal = info.get("channel") or info.get("uploader") or ""
    palabras = sum(len(t.split()) for _, t in lineas)
    L = [
        "---",
        f"titulo: {json.dumps(info.get('title') or '', ensure_ascii=False)}",
        f"canal: {json.dumps(canal, ensure_ascii=False)}",
        f"url: {url}",
        f"video_id: {vid}",
        f"publicado: {fecha}",
        f"duracion: {mmss(info.get('duration'))}",
        f"idioma: {lang or '?'}",
        f"fuente_transcripcion: {fuente}" + (f" ({os.path.basename(modelo)})" if modelo else ""),
        f"palabras: {palabras}",
        f"traido: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        "---",
        "",
        f"# {info.get('title') or vid}",
        "",
        f"{canal}, publicado {fecha}, {mmss(info.get('duration'))}. [Ver en YouTube]({url})",
        "",
    ]
    if fuente in ("auto", "whisper"):
        origen = "los subtítulos automáticos de YouTube" if fuente == "auto" else "whisper (local)"
        L += [f"> Transcripción de {origen}: puede equivocar nombres propios, comandos y términos "
              "técnicos. Contrástalos con la descripción, el repo enlazado o una captura antes de "
              "usarlos.", ""]
    desc = (info.get("description") or "").strip()
    if desc:
        L += ["## Descripción", "", "```text", desc, "```", ""]
    if caps:
        L += ["## Capítulos", ""]
        for c in caps:
            s = int(c.get("start_time", 0))
            L.append(f"- [{mmss(s)}](https://youtu.be/{vid}?t={s}) {c.get('title', '')}")
        L.append("")
    L += ["## Transcripción", ""]
    if not lineas:
        L += ["_(sin transcripción: el video no tiene subtítulos y su audio es silencio. Si es una "
              "grabación de pantalla, usa `capturas`.)_", ""]
    titulos = {int(c.get("start_time", 0)): c.get("title", "") for c in caps}
    ya = set()
    for seg, texto in parrafos(lineas, caps):
        for t0 in sorted(titulos):
            if t0 <= seg and t0 not in ya:
                L += [f"### {titulos[t0]}", ""]
                ya.add(t0)
        s = int(seg)
        L += [f"[{mmss(s)}](https://youtu.be/{vid}?t={s}) {texto}", ""]
    return "\n".join(L)


def cmd_transcribir(a):
    requiere("yt-dlp")
    url = limpiar_url(a.url)
    info = info_video(url)
    os.makedirs(a.salida, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="traer-de-youtube-")
    try:
        lang, tipo = (None, None) if a.whisper else elegir_subtitulos(info, a.idioma)
        modelo = None
        if lang:
            lineas = leer_vtt(bajar_vtt(url, lang, tipo, tmp))
            fuente = tipo
        else:
            lineas = transcribir_local(url, info, a.idioma, tmp)
            fuente, modelo = "whisper", modelo_whisper()
            lang = a.idioma or info.get("language") or "auto"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    fecha = info.get("upload_date") or "00000000"
    nombre = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:]}-{slug(info.get('title'))}-{info.get('id')}.md"
    ruta = os.path.join(a.salida, nombre)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(armar_md(info, url, fuente, lang, lineas, modelo))
    palabras = sum(len(t.split()) for _, t in lineas)
    print(ruta)
    print(f"fuente: {fuente}, idioma: {lang}, {palabras} palabras, "
          f"{len(info.get('chapters') or [])} capítulos, duración {mmss(info.get('duration'))}",
          file=sys.stderr)


# ================================================================= capturas

def cmd_capturas(a):
    requiere("yt-dlp", "ffmpeg")
    url = limpiar_url(a.url)
    info = info_video(url)
    dur = info.get("duration") or 0
    if a.en:
        tiempos = [a_segundos(t) for t in a.en.split(",") if t.strip()]
    else:
        tiempos = [float(t) for t in range(0, int(dur), max(1, int(a.cada)))]
    tiempos = [t for t in tiempos if 0 <= t < max(dur, 1)]
    if len(tiempos) > MAX_CAPTURAS:
        sys.exit(f"ERROR: son {len(tiempos)} capturas; el máximo es {MAX_CAPTURAS}. "
                 "Sube --cada o elige minutos con --en (mira los capítulos o la transcripción).")
    os.makedirs(a.salida, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="traer-de-youtube-")
    try:
        r = correr(["yt-dlp", "--no-playlist", "-f",
                    "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]/b",
                    "-o", os.path.join(tmp, "video.%(ext)s"), url])
        videos = [v for v in glob.glob(os.path.join(tmp, "video.*")) if not v.endswith(".part")]
        if not videos:
            sys.exit(f"ERROR: {pista_error(r.stderr)}")
        for t in tiempos:
            destino = os.path.join(a.salida, f"{info.get('id')}-{mmss(t).replace(':', '-')}.jpg")
            r = correr(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", str(t),
                        "-i", videos[0], "-frames:v", "1", "-q:v", "3", destino])
            if r.returncode == 0 and os.path.isfile(destino):
                print(destino)
            else:
                print(f"FALLÓ {mmss(t)}: {r.stderr.strip()[:160]}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ================================================================= audio y destinos

def unidades_extraibles():
    """Volúmenes montados que no son el disco interno. macOS: /Volumes; Linux: /media y /run/media."""
    candidatos = []
    if sys.platform == "darwin":
        for nombre in sorted(os.listdir("/Volumes")):
            ruta = os.path.join("/Volumes", nombre)
            if os.path.islink(ruta) or not os.path.ismount(ruta):
                continue  # "Macintosh HD" es un symlink a /
            r = subprocess.run(["diskutil", "info", "-plist", ruta], capture_output=True)
            try:
                d = plistlib.loads(r.stdout) if r.returncode == 0 else {}
            except Exception:
                d = {}
            if not d or d.get("Error"):
                continue
            if (not d.get("Internal", True)) or d.get("RemovableMediaOrExternalDevice") \
                    or d.get("Ejectable"):
                fs = d.get("FilesystemName") or d.get("FilesystemType") or "?"
                candidatos.append((ruta, fs, shutil.disk_usage(ruta).free))
    else:
        usuario = os.environ.get("USER", "")
        for base in (f"/media/{usuario}", f"/run/media/{usuario}", "/media"):
            if not os.path.isdir(base):
                continue
            for nombre in sorted(os.listdir(base)):
                ruta = os.path.join(base, nombre)
                if os.path.ismount(ruta) and all(c[0] != ruta for c in candidatos):
                    candidatos.append((ruta, "?", shutil.disk_usage(ruta).free))
    return candidatos


def bajar_mp3(url, carpeta):
    r = correr([
        "yt-dlp", "--no-playlist", "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-metadata", "--embed-thumbnail", "--windows-filenames",
        "-o", os.path.join(carpeta, "%(id)s.%(ext)s"),
        "--print", "after_move:filepath", url,
    ])
    rutas = [l.strip() for l in r.stdout.splitlines() if l.strip().endswith(".mp3")]
    if r.returncode != 0 or not rutas or not os.path.isfile(rutas[-1]):
        raise RuntimeError(pista_error(r.stderr))
    return rutas[-1]


def una_linea(s):
    return re.sub(r"[\t\r\n]+", " ", str(s or ""))


def cmd_bajar(a):
    requiere("yt-dlp", "ffmpeg")
    for url in a.urls:
        limpio = limpiar_url(url)
        try:
            info = info_video(limpio)
            archivo = bajar_mp3(limpio, a.carpeta)
            nombre = nombre_limpio(info.get("title"), info.get("id", "audio"))
            print("\t".join(["OK", archivo, una_linea(nombre), una_linea(info.get("title")),
                             una_linea(aviso_audio(info))]), flush=True)
        except Exception as e:
            print("\t".join(["FALLO", limpio, una_linea(e)]), flush=True)


def cmd_info(a):
    requiere("yt-dlp")
    for url in a.urls:
        limpio = limpiar_url(url)
        try:
            i = info_video(limpio)
            lang, tipo = elegir_subtitulos(i, None)
            subs = f"subtítulos {tipo} ({lang})" if lang else "sin subtítulos (iría por whisper)"
            caps = len(i.get("chapters") or [])
            print(f"{i.get('title')} | {mmss(i.get('duration'))} | "
                  f"{caps} capítulos | {subs}" + (f" | {aviso_audio(i)}" if not caps and
                                                   aviso_audio(i) else ""))
        except RuntimeError as e:
            print(f"FALLÓ {limpio}: {e}")


def cmd_destinos(_a):
    for ruta, fs, libre in unidades_extraibles():
        print(f"{ruta}\t{fs}\t{libre}")


def main():
    p = argparse.ArgumentParser(description="Trae de YouTube transcripciones, capturas o audio.",
                                epilog="Detalle de cada subcomando: traer.py SUBCOMANDO -h")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transcribir", help="transcripción a .md")
    t.add_argument("url")
    t.add_argument("--salida", default=".", help="carpeta del .md (por defecto, la actual)")
    t.add_argument("--idioma", help="código de idioma preferido (es, en...)")
    t.add_argument("--whisper", action="store_true", help="ignora subtítulos y transcribe en local")
    t.set_defaults(f=cmd_transcribir)

    c = sub.add_parser("capturas", help="fotogramas en minutos dados")
    c.add_argument("url")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--en", help="minutos separados por coma: 1:20,3:45,1:02:03")
    g.add_argument("--cada", type=float, help="una captura cada N segundos")
    c.add_argument("--salida", default=".", help="carpeta de las imágenes")
    c.set_defaults(f=cmd_capturas)

    i = sub.add_parser("info", help="título, duración, capítulos y subtítulos")
    i.add_argument("urls", nargs="+")
    i.set_defaults(f=cmd_info)

    d = sub.add_parser("destinos", help="unidades externas montadas")
    d.set_defaults(f=cmd_destinos)

    b = sub.add_parser("bajar", help="MP3 a una carpeta (lo usa audio-a-pendrive.sh)")
    b.add_argument("carpeta")
    b.add_argument("urls", nargs="+")
    b.set_defaults(f=cmd_bajar)

    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
