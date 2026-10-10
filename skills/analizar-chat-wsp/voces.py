#!/usr/bin/env python3
"""voces.py: transcribe un audio y separa a los hablantes, todo en local.

Uso:
    python3 voces.py grabacion.m4a -n 3            # 3 personas (recomendado fijar el número)
    python3 voces.py grabacion.m4a                 # número automático (tiende a agrupar de más)
    python3 voces.py grabacion.m4a -n 2 -o salida.txt
    python3 voces.py --instalar                    # solo preparar entorno y modelos

Salida: texto con un turno por línea, `[mm:ss-mm:ss] H0: ...`, y el tiempo hablado por voz.
Las voces salen como H0, H1, H2...: el modelo las distingue, no las reconoce. Los nombres
los pone el agente por contexto (quién pregunta, quién explica) y lo declara como inferido.

Cómo funciona:
  1. ffmpeg convierte el audio a WAV 16 kHz mono.
  2. whisper.cpp (whisper-cli, el mismo de wsp_dossier.py) transcribe con marcas por palabra.
  3. sherpa-onnx corre la segmentación de pyannote 3.0 (convertida a ONNX) y una huella de
     voz CAM++ para agrupar segmentos por hablante. Sin cuenta, sin token, sin red salvo la
     descarga única de los modelos.
  4. Cada palabra se asigna a la voz activa en su instante y se agrupan turnos.

Este archivo se ejecuta con el python3 del sistema (solo stdlib) y delega el paso 3 a un
entorno propio en ~/.cache/wsp-voces/ que se crea solo la primera vez (necesita `uv`).
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

BASE = Path(os.environ.get("WSP_VOCES_HOME", Path.home() / ".cache" / "wsp-voces"))
VENV = BASE / "venv"
PY = VENV / "bin" / "python"
SEG_DIR = BASE / "sherpa-onnx-pyannote-segmentation-3-0"
SEG_MODEL = SEG_DIR / "model.onnx"
EMB_MODEL = BASE / "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEG_URL = f"{REL}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMB_URL = f"{REL}/speaker-recongition-models/{EMB_MODEL.name}"  # sic: así se llama el release
WHISPER_MODELS = Path.home() / ".cache" / "whisper-models"
CACHE = BASE / "cache"


def sh(cmd, **kw):
    r = subprocess.run(cmd, text=True, capture_output=True, **kw)
    if r.returncode != 0:
        sys.exit(f"falló: {' '.join(map(str, cmd))}\n{r.stderr.strip()[-2000:]}")
    return r.stdout


def descargar(url, destino):
    if destino.exists() and destino.stat().st_size > 1000:
        return
    print(f"descargando {url.rsplit('/', 1)[-1]} ...", file=sys.stderr)
    sh(["curl", "-sSL", "--fail", "-o", str(destino), url])


def instalar():
    for herramienta in ("ffmpeg", "whisper-cli", "uv"):
        if not shutil.which(herramienta):
            paquete = "whisper-cpp" if herramienta == "whisper-cli" else herramienta
            sys.exit(f"falta `{herramienta}` (brew install {paquete})")
    BASE.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    if not PY.exists():
        print("creando entorno en", VENV, file=sys.stderr)
        sh(["uv", "venv", "-q", "-p", "3.12", str(VENV)])
    try:
        subprocess.run([PY, "-c", "import sherpa_onnx, soundfile, numpy"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("instalando sherpa-onnx ...", file=sys.stderr)
        sh(["uv", "pip", "install", "-q", "-p", str(PY), "sherpa-onnx", "numpy", "soundfile"])
    if not SEG_MODEL.exists():
        tarball = BASE / "seg.tar.bz2"
        descargar(SEG_URL, tarball)
        sh(["tar", "xf", str(tarball), "-C", str(BASE)])
        tarball.unlink()
    descargar(EMB_URL, EMB_MODEL)


def a_wav(audio, wav):
    sh(["ffmpeg", "-v", "error", "-y", "-i", str(audio), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])


def transcribir(wav, modelo, idioma):
    modelo_bin = WHISPER_MODELS / f"ggml-{modelo}.bin"
    if not modelo_bin.exists():
        sys.exit(f"falta el modelo de whisper {modelo_bin} (ver HERRAMIENTA.md)")
    clave = hashlib.sha256(wav.read_bytes()).hexdigest()[:16] + f"-{modelo}-{idioma}"
    cacheado = CACHE / f"{clave}.json"
    if cacheado.exists():
        return json.loads(cacheado.read_text())
    salida = wav.with_suffix("")
    sh(["whisper-cli", "-m", str(modelo_bin), "-f", str(wav), "-l", idioma, "--no-prints",
        "-ml", "1", "-sow", "-oj", "-of", str(salida)])
    datos = json.loads(Path(str(salida) + ".json").read_text())["transcription"]
    cacheado.write_text(json.dumps(datos))
    return datos


def diarizar(wav, n, umbral):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        salida = Path(f.name)
    sh([str(PY), "-I", __file__, "_diarizar", str(wav), str(salida), str(n), str(umbral)])
    return json.loads(salida.read_text())


def _diarizar_en_venv(wav, salida, n, umbral):
    import sherpa_onnx
    import soundfile as sf
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(SEG_MODEL))),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(EMB_MODEL)),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=n, threshold=umbral),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    audio, sr = sf.read(wav, dtype="float32", always_2d=True)
    assert sr == sd.sample_rate, f"el wav debe ser {sd.sample_rate} Hz"
    segs = [{"start": s.start, "end": s.end, "spk": s.speaker}
            for s in sd.process(audio[:, 0]).sort_by_start_time()]
    Path(salida).write_text(json.dumps(segs))


def fusionar(palabras, segs, pausa=2.0, tolerancia=3.0):
    def voz_en(t):
        mejor, dist = None, 1e9
        for s in segs:
            if s["start"] <= t <= s["end"]:
                return s["spk"]
            d = min(abs(t - s["start"]), abs(t - s["end"]))
            if d < dist:
                mejor, dist = s["spk"], d
        return mejor if dist < tolerancia else "?"
    turnos = []
    for p in palabras:
        t0, t1 = p["offsets"]["from"] / 1000, p["offsets"]["to"] / 1000
        voz = voz_en((t0 + t1) / 2)
        if turnos and turnos[-1]["voz"] == voz and t0 - turnos[-1]["fin"] < pausa:
            turnos[-1]["texto"] += p["text"]
            turnos[-1]["fin"] = t1
        else:
            turnos.append({"voz": voz, "ini": t0, "fin": t1, "texto": p["text"]})
    return turnos


def mmss(s):
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audio", nargs="?", help="m4a, opus, mp3, wav, mp4...")
    ap.add_argument("-n", "--hablantes", type=int, default=-1, help="número de voces; sin él, automático")
    ap.add_argument("-t", "--umbral", type=float, default=0.9,
                    help="umbral de agrupación en modo automático (más alto = menos voces)")
    ap.add_argument("-m", "--modelo", default="large-v3-turbo-q5_0")
    ap.add_argument("-l", "--idioma", default="es")
    ap.add_argument("-o", "--salida", help="archivo .txt (default: imprime)")
    ap.add_argument("--instalar", action="store_true", help="solo preparar entorno y modelos")
    args = ap.parse_args()

    instalar()
    if args.instalar or not args.audio:
        print("entorno listo en", BASE, file=sys.stderr)
        return
    audio = Path(args.audio).expanduser().resolve()
    if not audio.exists():
        sys.exit(f"no existe {audio}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        a_wav(audio, wav)
        palabras = transcribir(wav, args.modelo, args.idioma)
        segs = diarizar(wav, args.hablantes, args.umbral)
    turnos = fusionar(palabras, segs)
    total = Counter()
    for t in turnos:
        total[t["voz"]] += t["fin"] - t["ini"]
    voces = sorted(total, key=lambda v: (v == "?", str(v)))
    modo = "fijadas" if args.hablantes > 0 else "automático"
    lineas = [f"# {audio.name}: {mmss(turnos[-1]['fin']) if turnos else '00:00'}, "
              f"{len(voces) - ('?' in voces)} voces ({modo}), modelo {args.modelo}. "
              "Transcripción automática, no acta. H? = sin asignar.",
              "# tiempo hablado: " + ", ".join(f"H{v}={mmss(total[v])}" for v in voces), ""]
    lineas += [f"[{mmss(t['ini'])}-{mmss(t['fin'])}] H{t['voz']}: {t['texto'].strip()}" for t in turnos]
    texto = "\n".join(lineas) + "\n"
    if args.salida:
        Path(args.salida).write_text(texto)
        print(args.salida)
    else:
        sys.stdout.write(texto)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_diarizar":
        _, _, wav, salida, n, umbral = sys.argv
        _diarizar_en_venv(wav, salida, int(n), float(umbral))
    else:
        main()
