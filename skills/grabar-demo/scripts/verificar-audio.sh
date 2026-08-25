#!/bin/bash
# Verifica que una pista musical NO tenga locución antes de montarla en un demo.
# Uso: ./verificar-audio.sh <pista> [idioma=es]
#
# Motivo real (20/08/2026): la pista candidata venía de un video de otro cliente
# hecho en iMovie. Si traía voz nombrando a ese cliente, el demo lo habría llevado
# adentro. Se verifica SIEMPRE, aunque la pista "suene instrumental".
#
# Qué hace:
#   1. Niveles y dinámica (una locución da picos y valles muy marcados).
#   2. Transcripción con whisper.cpp de tres tramos (inicio, medio, final).
# Lo que devuelve NO decide solo: si aparece texto coherente y repetido, hay voz.
# Un audio sin voz suele devolver frases alucinadas típicas ("Subtítulos por...",
# "Gracias por ver el video") o silencio.
set -euo pipefail
PISTA="$1"; IDIOMA="${2:-es}"
MODELO="${WHISPER_MODELO:-$HOME/.cache/whisper-models/ggml-large-v3-turbo-q5_0.bin}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$PISTA")
echo "Pista: $PISTA"
echo "Duración: ${D}s"
echo "--- Niveles ---"
ffmpeg -hide_banner -nostats -i "$PISTA" -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume' | sed 's/^.*\] //' || true

if [[ -x "$(command -v whisper-cli)" && -f "$MODELO" ]]; then
  echo "--- Transcripción de control (3 tramos de 45s) ---"
  for OFF in 0 $(python3 -c "print(max(0,int($D/2)-22))") $(python3 -c "print(max(0,int($D)-50))"); do
    ffmpeg -v error -ss "$OFF" -t 45 -i "$PISTA" -ar 16000 -ac 1 -c:a pcm_s16le "$TMP/s.wav" -y
    echo "· tramo desde ${OFF}s:"
    whisper-cli -m "$MODELO" -l "$IDIOMA" -nt -np -f "$TMP/s.wav" 2>/dev/null | tr -s '\n' | sed 's/^/    /' | head -12
    echo
  done
else
  echo "whisper-cli o el modelo no están disponibles: verifica la pista escuchándola completa."
fi
echo
echo "Decide: ¿hay voz humana con contenido? Si hay dudas, NO uses la pista."
echo "Y si el video va a redes, confirma también la licencia de la música."
