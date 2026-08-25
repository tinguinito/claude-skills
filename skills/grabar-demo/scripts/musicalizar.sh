#!/bin/bash
# Música de fondo sobre un video ya montado: bucle, fundido de entrada y de salida.
# Uso: ./musicalizar.sh <video> <salida> <pista> [volumen=0.32]
# El volumen 0.32 deja la música cerca de -23 dBFS de media (fondo, no protagonista).
# ⚠️ Corre antes verificar-audio.sh sobre la pista: una pista con locución de otro
#    cliente dentro es un error que no se nota hasta que el cliente lo escucha.
set -euo pipefail
IN="$1"; OUT="$2"; PISTA="$3"; VOL="${4:-0.32}"
D=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")
FO=$(python3 -c "print(max(0,$D-2.2))")
ffmpeg -v error -i "$IN" -stream_loop -1 -i "$PISTA" \
  -filter_complex "[1:a]volume=${VOL},afade=t=in:st=0:d=1.8,afade=t=out:st=${FO}:d=2.2[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 160k -shortest -movflags +faststart "$OUT" -y
echo "$OUT"
