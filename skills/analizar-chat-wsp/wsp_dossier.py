#!/usr/bin/env python3
"""
wsp-dossier — convierte un export de WhatsApp (zip o carpeta) en un dossier
markdown legible: el chat linealizado con los audios ya transcritos inline y
las imagenes listadas con su ruta para que el agente las lea directo.

Transcripcion 100% local con whisper.cpp (Metal en Apple Silicon). Sin API,
sin costo, sin que el contenido privado salga del Mac.

Uso:
    python3 wsp_dossier.py "~/Downloads/WhatsApp Chat - Nombre.zip"
    python3 wsp_dossier.py entrada.zip --salida ~/ruta/dossier.md
    python3 wsp_dossier.py entrada.zip --modelo medium   # mas rapido, menos preciso

Requisitos: brew install whisper-cpp ffmpeg  +  un modelo ggml en MODELOS_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

MODELOS_DIR = Path.home() / ".cache" / "whisper-models"
CACHE_DIR = Path.home() / ".cache" / "wsp-dossier"
MODELO_DEFECTO = "large-v3-turbo-q5_0"  # medido 17/08/2026 (35 audios reales): el turbo es igual o mejor para notas de voz de WhatsApp;
# large-v3-q5_0 queda instalado para audio largo/limpio via --modelo large-v3-q5_0

EXT_AUDIO = {".opus", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".amr", ".mp4a"}
EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif"}
EXT_VIDEO = {".mp4", ".mov", ".3gp", ".avi", ".mkv"}

# Formato iOS:      [23-07-26, 10:44:03] Autor: texto
# Formato Android:  23/07/2026, 10:44 - Autor: texto
RE_LINEA_IOS = re.compile(
    r"^‎?\[(?P<fecha>\d{1,2}[-/]\d{1,2}[-/]\d{2,4}),\s*(?P<hora>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[ap]\.?\s?m\.?)?\]\s*"
    r"(?P<autor>[^:]{1,80}?):\s?(?P<texto>.*)$",
    re.IGNORECASE,
)
RE_LINEA_ANDROID = re.compile(
    r"^(?P<fecha>\d{1,2}/\d{1,2}/\d{2,4}),\s*(?P<hora>\d{1,2}:\d{2}(?::\d{2})?)\s*(?P<ampm>[ap]\.?\s?m\.?)?\s*-\s*"
    r"(?P<autor>[^:]{1,80}?):\s?(?P<texto>.*)$",
    re.IGNORECASE,
)
# <adjunto: archivo.opus>  /  archivo.opus (file attached)
RE_ADJUNTO = re.compile(
    r"[<‎]*\s*(?:adjunto|attached|archivo adjunto)\s*:\s*(?P<nombre>[^>\n]+?)\s*>"
    r"|(?P<nombre2>[\w\-. ]+\.\w{2,5})\s*\((?:archivo adjunto|file attached)\)",
    re.IGNORECASE,
)
# Ruido que WhatsApp inserta y no aporta al analisis
RUIDO = (
    "los mensajes y las llamadas están cifrados",
    "messages and calls are end-to-end encrypted",
    "es un contacto.",
    "is a contact.",
)


@dataclass
class Mensaje:
    fecha: str
    hora: str
    autor: str
    texto: str
    adjunto: str | None = None
    tipo: str = "texto"        # texto | audio | imagen | video | documento
    transcripcion: str | None = None
    continuacion: list[str] = field(default_factory=list)

    @property
    def cuerpo(self) -> str:
        partes = [self.texto] + self.continuacion
        return "\n".join(p for p in partes if p.strip())


# ---------------------------------------------------------------- utilidades

def log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr, flush=True)


def requiere(binario: str, ayuda: str) -> None:
    if shutil.which(binario) is None:
        sys.exit(f"error: falta '{binario}'. Instalalo con: {ayuda}")


def sha_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()[:16]


def preparar_entrada(entrada: Path, destino: Path) -> Path:
    """Devuelve la carpeta con los archivos del export (extrae si es zip)."""
    if entrada.is_dir():
        return entrada
    if entrada.suffix.lower() != ".zip":
        sys.exit(f"error: '{entrada}' no es un .zip ni una carpeta")
    destino.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(entrada) as z:
        z.extractall(destino)
    return destino


def hallar_chat_txt(carpeta: Path) -> Path:
    candidatos = sorted(carpeta.rglob("*.txt"))
    if not candidatos:
        sys.exit(f"error: no encontre ningun .txt en {carpeta}")
    # WhatsApp lo llama _chat.txt (iOS) o "Chat de WhatsApp con X.txt" (Android)
    for c in candidatos:
        if c.name == "_chat.txt":
            return c
    return max(candidatos, key=lambda p: p.stat().st_size)


def clasificar(nombre: str) -> str:
    ext = Path(nombre).suffix.lower()
    if ext in EXT_AUDIO:
        return "audio"
    if ext in EXT_IMAGEN:
        return "imagen"
    if ext in EXT_VIDEO:
        return "video"
    return "documento"


# ------------------------------------------------------------------- parseo

def parsear_chat(ruta_txt: Path) -> tuple[list[Mensaje], str]:
    crudo = ruta_txt.read_text(encoding="utf-8", errors="replace")
    mensajes: list[Mensaje] = []
    formato = "desconocido"

    for linea in crudo.splitlines():
        linea = linea.replace("‎", "").replace("‏", "").rstrip()
        if not linea:
            continue

        m = RE_LINEA_IOS.match(linea)
        if m:
            formato = "ios"
        else:
            m = RE_LINEA_ANDROID.match(linea)
            if m:
                formato = "android"

        if not m:
            # linea de continuacion de un mensaje multilinea
            if mensajes:
                mensajes[-1].continuacion.append(linea)
            continue

        texto = m.group("texto").strip()
        if any(r in texto.lower() for r in RUIDO):
            continue

        msg = Mensaje(
            fecha=m.group("fecha"),
            hora=m.group("hora"),
            autor=m.group("autor").strip(),
            texto=texto,
        )

        adj = RE_ADJUNTO.search(texto)
        if adj:
            nombre = (adj.group("nombre") or adj.group("nombre2") or "").strip()
            if nombre:
                msg.adjunto = nombre
                msg.tipo = clasificar(nombre)
                msg.texto = ""
        mensajes.append(msg)

    return mensajes, formato


# ------------------------------------------------------------- transcripcion

def ruta_modelo(nombre: str) -> Path:
    directo = MODELOS_DIR / nombre
    if directo.is_file():
        return directo
    candidato = MODELOS_DIR / f"ggml-{nombre}.bin"
    if candidato.is_file():
        return candidato
    disponibles = sorted(p.name for p in MODELOS_DIR.glob("*.bin")) if MODELOS_DIR.is_dir() else []
    sys.exit(
        f"error: no encontre el modelo '{nombre}' en {MODELOS_DIR}\n"
        f"  disponibles: {disponibles or 'ninguno'}\n"
        f"  descarga: curl -L -o {MODELOS_DIR}/ggml-{nombre}.bin \\\n"
        f'    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{nombre}.bin?download=true"'
    )


def transcribir(audio: Path, modelo: Path, idioma: str, hilos: int) -> str:
    """Transcribe un audio con whisper.cpp. Cachea por hash de contenido."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    clave = f"{sha_archivo(audio)}-{modelo.stem}-{idioma}"
    cache = CACHE_DIR / f"{clave}.txt"
    if cache.is_file():
        log(f"cache  {audio.name}")
        return cache.read_text(encoding="utf-8").strip()

    log(f"transcribiendo {audio.name} ...")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(audio),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
            capture_output=True, text=True,
        )
        if r.returncode != 0 or not wav.is_file():
            return f"[ERROR ffmpeg: {r.stderr.strip()[:200]}]"

        salida = Path(tmp) / "out"
        r = subprocess.run(
            ["whisper-cli", "-m", str(modelo), "-f", str(wav), "-l", idioma,
             "-t", str(hilos), "--output-txt", "--output-file", str(salida),
             "--no-prints"],
            capture_output=True, text=True,
        )
        txt = salida.with_suffix(".txt")
        if r.returncode != 0 or not txt.is_file():
            return f"[ERROR whisper: {(r.stderr or r.stdout).strip()[:200]}]"

        texto = " ".join(txt.read_text(encoding="utf-8").split()).strip()

    cache.write_text(texto, encoding="utf-8")
    return texto or "[audio sin habla detectable]"


# ------------------------------------------------------------------- salida

def construir_dossier(mensajes: list[Mensaje], carpeta: Path, titulo: str,
                      formato: str, modelo: Path) -> str:
    autores: dict[str, int] = {}
    for m in mensajes:
        autores[m.autor] = autores.get(m.autor, 0) + 1

    conteo = {t: sum(1 for m in mensajes if m.tipo == t)
              for t in ("texto", "audio", "imagen", "video", "documento")}
    imagenes = [m for m in mensajes if m.tipo == "imagen"]
    documentos = [m for m in mensajes if m.tipo == "documento"]

    L: list[str] = []
    L.append(f"# Dossier de chat WhatsApp — {titulo}")
    L.append("")
    hablado = conteo["audio"] + conteo["video"]
    # La cabecera describe lo que REALMENTE se transcribió, no lo que venía en el export:
    # con --sin-video hay videos en el chat pero ninguno tiene transcripción.
    video_transcrito = any(m.tipo == "video" and m.transcripcion for m in mensajes)
    if hablado and modelo.name != "null":
        que = "Audios y videos transcritos" if video_transcrito else "Audios transcritos"
        L.append(f"> Generado por `wsp-dossier`. {que} localmente con "
                 f"whisper.cpp (`{modelo.name}`). Formato de export detectado: {formato}.")
        L.append("> Las transcripciones son automáticas: verifica una cita literal "
                 "contra el audio antes de usarla como prueba.")
    else:
        nota = ("audios sin transcribir (modo `--sin-audio`)" if hablado
                else "este export no trae audios ni videos")
        L.append(f"> Generado por `wsp-dossier`: {nota}. "
                 f"Formato de export detectado: {formato}.")
    L.append("")
    L.append("## Resumen del material")
    L.append("")
    L.append(f"- **Mensajes:** {len(mensajes)}")
    L.append(f"- **Participantes:** " + ", ".join(f"{a} ({n})" for a, n in
             sorted(autores.items(), key=lambda kv: -kv[1])))
    L.append("- **Adjuntos:** " + ", ".join(f"{k} {v}" for k, v in conteo.items() if v) or "- **Adjuntos:** ninguno")
    if mensajes:
        L.append(f"- **Rango:** {mensajes[0].fecha} {mensajes[0].hora} → "
                 f"{mensajes[-1].fecha} {mensajes[-1].hora}")
    L.append("")

    if imagenes:
        L.append("## Imágenes — leerlas con el tool `Read`")
        L.append("")
        L.append("El script no interpreta imágenes: el agente las ve directo, sin API ni costo.")
        L.append("")
        for m in imagenes:
            L.append(f"- `{(carpeta / m.adjunto)}` — enviada por {m.autor}, {m.fecha} {m.hora}")
        L.append("")

    if documentos:
        L.append("## Documentos — leerlos con el tool `Read`")
        L.append("")
        L.append("El script no los interpreta: el agente abre PDF, docx y planillas directo.")
        L.append("Una cotización o una ficha técnica adjunta suele traer el dato duro del chat.")
        L.append("")
        for m in documentos:
            L.append(f"- `{(carpeta / m.adjunto)}` — enviado por {m.autor}, {m.fecha} {m.hora}")
        L.append("")

    L.append("## Conversación completa")
    L.append("")
    fecha_actual = None
    for m in mensajes:
        if m.fecha != fecha_actual:
            fecha_actual = m.fecha
            L.append("")
            L.append(f"### {fecha_actual}")
            L.append("")

        cabecera = f"**[{m.hora}] {m.autor}:**"
        if m.tipo == "audio":
            L.append(f"{cabecera} 🎙️ _audio_ (`{m.adjunto}`)")
            L.append("")
            L.append(f"> {m.transcripcion or '[sin transcribir]'}")
            L.append("")
        elif m.tipo == "imagen":
            L.append(f"{cabecera} 🖼️ _imagen_ → `{m.adjunto}` (ver sección Imágenes)")
        elif m.tipo == "video":
            L.append(f"{cabecera} 🎬 _video_ (`{m.adjunto}`)")
            L.append("")
            L.append(f"> {m.transcripcion or '[video sin transcribir]'}")
            L.append("")
        elif m.tipo == "documento":
            L.append(f"{cabecera} 📎 _documento_ → `{m.adjunto}` (ver sección Documentos)")
        else:
            cuerpo = m.cuerpo
            if "\n" in cuerpo:
                L.append(cabecera)
                L.append("")
                for linea in cuerpo.splitlines():
                    L.append(f"> {linea}")
                L.append("")
            else:
                L.append(f"{cabecera} {cuerpo}")

    L.append("")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convierte un export de WhatsApp en un dossier markdown con audios transcritos.")
    ap.add_argument("entrada", help="ruta al .zip exportado por WhatsApp, o a una carpeta ya extraida")
    ap.add_argument("--salida", "-o", help="ruta del .md de salida (default: junto a la entrada)")
    ap.add_argument("--modelo", "-m", default=MODELO_DEFECTO,
                    help=f"modelo ggml en {MODELOS_DIR} (default: {MODELO_DEFECTO})")
    ap.add_argument("--idioma", "-l", default="es", help="idioma del audio (default: es)")
    ap.add_argument("--hilos", "-t", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--sin-audio", action="store_true", help="no transcribir (solo texto y listado)")
    ap.add_argument("--sin-video", action="store_true",
                    help="no transcribir el audio de los videos (pueden ser largos y lentos)")
    ap.add_argument("--json", dest="json_out", help="además, volcar los mensajes a este .json")
    args = ap.parse_args()

    entrada = Path(os.path.expanduser(args.entrada)).resolve()
    if not entrada.exists():
        sys.exit(f"error: no existe '{entrada}'")

    requiere("ffmpeg", "brew install ffmpeg")
    modelo = Path("/dev/null")
    if not args.sin_audio:
        requiere("whisper-cli", "brew install whisper-cpp")
        modelo = ruta_modelo(args.modelo)

    titulo = entrada.stem.replace("WhatsApp Chat - ", "").strip()
    salida = Path(os.path.expanduser(args.salida)).resolve() if args.salida else \
        entrada.parent / f"dossier-{re.sub(r'[^a-zA-Z0-9]+', '-', titulo).strip('-').lower()}.md"

    # Un zip se extrae junto a la salida, para que las rutas de las imagenes
    # que el agente va a leer sigan existiendo despues de correr el script.
    carpeta = preparar_entrada(entrada, salida.parent / f"{salida.stem}-media")
    log(f"material en {carpeta}")

    mensajes, formato = parsear_chat(hallar_chat_txt(carpeta))
    log(f"{len(mensajes)} mensajes parseados (formato {formato})")

    if not args.sin_audio:
        # Los videos también se transcriben: ffmpeg extrae la pista de audio de un .mp4 con el
        # MISMO comando que usa para un .opus, así que no hacen falta dos rutas de código.
        # Antes solo se listaban, y el contenido hablado del video se perdía del dossier: en un
        # chat de trabajo, un video de alguien mostrando algo a cámara suele traer el dato clave.
        tipos = ["audio"] if args.sin_video else ["audio", "video"]
        audios = [m for m in mensajes if m.tipo in tipos]
        for i, m in enumerate(audios, 1):
            ruta = carpeta / m.adjunto
            if not ruta.is_file():
                # el export a veces anida el media en subcarpetas
                hallado = next(carpeta.rglob(m.adjunto), None)
                if hallado is None:
                    m.transcripcion = "[archivo de audio no encontrado en el export]"
                    continue
                ruta = hallado
            log(f"[{i}/{len(audios)}]")
            m.transcripcion = transcribir(ruta, modelo, args.idioma, args.hilos)

    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(construir_dossier(mensajes, carpeta, titulo, formato, modelo),
                      encoding="utf-8")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            [{k: v for k, v in m.__dict__.items() if k != "continuacion"} | {"cuerpo": m.cuerpo}
             for m in mensajes], ensure_ascii=False, indent=2), encoding="utf-8")

    print(salida)


if __name__ == "__main__":
    main()
