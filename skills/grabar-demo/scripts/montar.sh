#!/bin/bash
# Montaje del demo: normaliza, recorta el marco del navegador si lo hubiera,
# acelera y agrega logo de entrada (del cliente) y de cierre (propio), con fundidos.
#
# Uso:
#   ./montar.sh --in demo.webm --out demo.mp4 [opciones]
#
# Opciones:
#   --crop W:H:X:Y       recorte (obligatorio si el material viene de captura de pantalla)
#   --speed 1.6          factor de aceleración (1 = sin cambio)
#   --logo-intro RUTA    logo del cliente al inicio (opcional)
#   --logo-cierre RUTA   logo de cierre (por defecto: assets/logo-cierre.png, si existe)
#   --ancho-intro 620    ancho del logo de intro en px
#   --ancho-cierre 520   ancho del logo de cierre en px
#   --dur-logo 2.6       duración de cada placa de logo, en segundos
#   --fondo white        color de fondo de las placas
#   --fps 50
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IN=""; OUT=""; CROP=""; SPEED="1"; LOGO_IN=""; LOGO_OUT="$AQUI/../assets/logo-cierre.png"
AW_IN="620"; AW_OUT="520"; DUR="2.6"; FONDO="white"; FPS="50"; DESDE=""; HASTA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --in) IN="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --desde) DESDE="$2"; shift 2;;
    --hasta) HASTA="$2"; shift 2;;
    --crop) CROP="$2"; shift 2;;
    --speed) SPEED="$2"; shift 2;;
    --logo-intro) LOGO_IN="$2"; shift 2;;
    --logo-cierre) LOGO_OUT="$2"; shift 2;;
    --ancho-intro) AW_IN="$2"; shift 2;;
    --ancho-cierre) AW_OUT="$2"; shift 2;;
    --dur-logo) DUR="$2"; shift 2;;
    --fondo) FONDO="$2"; shift 2;;
    --fps) FPS="$2"; shift 2;;
    --sin-cierre) LOGO_OUT=""; shift;;
    *) echo "Opción desconocida: $1" >&2; exit 1;;
  esac
done
[[ -n "$IN" && -n "$OUT" ]] || { echo "Faltan --in y --out" >&2; exit 1; }

# Dimensiones finales: las del recorte si hay recorte, si no las del original.
if [[ -n "$CROP" ]]; then
  W="${CROP%%:*}"; R="${CROP#*:}"; H="${R%%:*}"
else
  W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 "$IN")
  H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 "$IN")
fi
# libx264 exige dimensiones pares.
W=$(( W / 2 * 2 )); H=$(( H / 2 * 2 ))

INPUTS=(); FILTROS=(); PARTES=(); N=0
CADENA_MAIN=""
[[ -n "$CROP" ]] && CADENA_MAIN+="crop=${CROP},"
CADENA_MAIN+="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=${FONDO},"
[[ "$SPEED" != "1" ]] && CADENA_MAIN+="setpts=PTS/${SPEED},"
CADENA_MAIN+="fps=${FPS},setsar=1,fade=t=in:st=0:d=0.4"

placa() { # $1 = ruta logo, $2 = ancho, $3 = etiqueta
  local logo="$1" ancho="$2" tag="$3"
  INPUTS+=(-f lavfi -i "color=c=${FONDO}:s=${W}x${H}:r=${FPS}:d=${DUR}"); local iFondo=$N; N=$((N+1))
  INPUTS+=(-i "$logo"); local iLogo=$N; N=$((N+1))
  local salida_fade; salida_fade=$(python3 -c "print(round($DUR-0.5,2))")
  FILTROS+=("[${iLogo}]scale=${ancho}:-1:flags=lanczos[${tag}l];[${iFondo}][${tag}l]overlay=(W-w)/2:(H-h)/2,fade=t=in:st=0:d=0.5,fade=t=out:st=${salida_fade}:d=0.5,setsar=1[${tag}]")
  PARTES+=("[${tag}]")
}

[[ -n "$LOGO_IN" ]] && placa "$LOGO_IN" "$AW_IN" intro
# --desde / --hasta recortan en el tiempo (por ejemplo, dejar fuera el login de
# desarrollo con el que arranca el guion). Van antes de -i para que ffmpeg no
# decodifique lo que se descarta.
RECORTE=()
[[ -n "$DESDE" ]] && RECORTE+=(-ss "$DESDE")
[[ -n "$HASTA" ]] && RECORTE+=(-to "$HASTA")
INPUTS+=(${RECORTE[@]+"${RECORTE[@]}"} -i "$IN"); iMain=$N; N=$((N+1))
FILTROS+=("[${iMain}:v]${CADENA_MAIN}[main]")
PARTES+=("[main]")
[[ -n "$LOGO_OUT" ]] && placa "$LOGO_OUT" "$AW_OUT" outro

# El concat exige orden intro → main → outro; placa() agregó outro al final, pero
# intro quedó antes de main solo si se pidió, así que el arreglo ya está en orden.
GRAFO="$(IFS=';'; echo "${FILTROS[*]}");$(IFS=''; echo "${PARTES[*]}")concat=n=${#PARTES[@]}:v=1:a=0[v]"

ffmpeg -v error -stats "${INPUTS[@]}" -filter_complex "$GRAFO" \
  -map "[v]" -an -c:v libx264 -pix_fmt yuv420p -crf 21 -preset medium -movflags +faststart "$OUT" -y
echo "$OUT"
