#!/usr/bin/env bash
# Baja el audio de links de YouTube como MP3 y lo deja en un pendrive o tarjeta SD.
#
# USO
#   bash audio-a-pendrive.sh URL [URL ...]               # destino: la única unidad externa montada
#   bash audio-a-pendrive.sh --destino RUTA URL [...]    # carpeta explícita (crea la última carpeta)
#   bash audio-a-pendrive.sh --listar-destinos           # qué unidades externas ve, no baja nada
#   bash audio-a-pendrive.sh --solo-info URL [...]       # título, duración y aviso, sin bajar
#
# Requiere yt-dlp, ffmpeg/ffprobe y python3 (y deno para que yt-dlp resuelva los desafíos JS de
# YouTube).
#
# REPARTO
#   traer.py resuelve los links, baja a una carpeta temporal del disco interno y arma el
#   nombre limpio. Este script copia al pendrive y verifica. La copia vive aquí y no en Python
#   porque en macOS todo archivo creado por un proceso hijo de Python (incluido un `cp -X` lanzado
#   desde Python) queda con `com.apple.provenance`, y en FAT32 eso deja un `._nombre.mp3` oculto
#   por canción que muchas radios de auto listan como pista rota. Desde bash, `cp -X` no lo deja.

set -uo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=(python3 -I "$AQUI/traer.py")
DESTINO=""; MODO="bajar"; URLS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --destino)         DESTINO="${2:-}"; shift 2 ;;
    --listar-destinos) MODO="destinos"; shift ;;
    --solo-info)       MODO="info"; shift ;;
    -h|--help)         sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)                echo "Opción desconocida: $1"; exit 1 ;;
    *)                 URLS+=("$1"); shift ;;
  esac
done

listar() { awk -F'\t' '{printf "  %s  (%s, %.1f GB libres)\n", $1, $2, $3/1e9}'; }

if [ "$MODO" = "destinos" ]; then
  U="$("${PY[@]}" destinos)"
  if [ -z "$U" ]; then echo "No hay unidades externas montadas."; else printf '%s\n' "$U" | listar; fi
  exit 0
fi
[ "${#URLS[@]}" -eq 0 ] && { echo "Falta al menos un link."; exit 1; }
if [ "$MODO" = "info" ]; then "${PY[@]}" info "${URLS[@]}"; exit 0; fi

for h in yt-dlp ffmpeg ffprobe python3; do
  command -v "$h" >/dev/null || { echo "ERROR: falta $h en el PATH"; exit 1; }
done

# ---------------------------------------------------------------- destino
if [ -z "$DESTINO" ]; then
  U="$("${PY[@]}" destinos)"
  N="$(printf '%s' "$U" | grep -c .)"
  if [ "$N" -eq 0 ]; then
    echo "ERROR: no veo ningún pendrive ni tarjeta montada. Conéctalo o usa --destino RUTA."; exit 1
  elif [ "$N" -gt 1 ]; then
    echo "ERROR: hay más de una unidad externa, elige con --destino:"; printf '%s\n' "$U" | listar; exit 1
  fi
  DESTINO="$(printf '%s' "$U" | cut -f1)"
fi
DESTINO="${DESTINO%/}"
if [ ! -d "$DESTINO" ]; then
  [ -d "$(dirname "$DESTINO")" ] || { echo "ERROR: no existe $(dirname "$DESTINO")"; exit 1; }
  mkdir "$DESTINO" || exit 1   # desde bash, para que la carpeta tampoco quede marcada
fi
echo "Destino: $DESTINO"

if [ "$(uname)" = "Darwin" ]; then
  copiar() { cp -X "$1" "$2"; }
  huella() { md5 -q "$1"; }
else
  copiar() { cp "$1" "$2"; }
  huella() { md5sum "$1" | cut -d' ' -f1; }
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/traer-de-youtube.XXXXXX")" || exit 1
trap 'rm -rf -- "${TMP:?}"' EXIT

# ---------------------------------------------------------------- bajar, copiar, verificar
FALLOS=0; DISTINTAS=0
REGISTRO="$TMP/copiadas.tsv"; : > "$REGISTRO"   # huella<TAB>ruta de cada copia, para el final
while IFS=$'\t' read -r ESTADO A B C D; do
  if [ "$ESTADO" != "OK" ]; then
    echo "FALLÓ $A: $B"; FALLOS=$((FALLOS + 1)); continue
  fi
  ORIGEN="$A"; NOMBRE="$B"; TITULO="$C"; AVISO="${D:-}"

  FINAL="$DESTINO/$NOMBRE.mp3"; n=2
  while [ -e "$FINAL" ]; do FINAL="$DESTINO/$NOMBRE ($n).mp3"; n=$((n + 1)); done

  TAM="$(wc -c < "$ORIGEN" | tr -d ' ')"
  LIBRE="$(df -Pk "$DESTINO" | awk 'NR==2 {print $4 * 1024}')"
  if [ "$TAM" -gt "${LIBRE%.*}" ]; then
    echo "FALLÓ $NOMBRE: no queda espacio en el destino"; FALLOS=$((FALLOS + 1)); continue
  fi

  copiar "$ORIGEN" "$FINAL" || { echo "FALLÓ $NOMBRE: no se pudo copiar"; FALLOS=$((FALLOS + 1)); continue; }
  SOMBRA="$(dirname "$FINAL")/._$(basename "$FINAL")"
  if [ -e "$SOMBRA" ] && command -v xattr >/dev/null; then xattr -c "$FINAL"; fi
  sync

  H="$(huella "$ORIGEN")"
  if [ "$H" != "$(huella "$FINAL")" ]; then
    rm -f -- "${FINAL:?}"
    echo "FALLÓ $NOMBRE: la copia no coincide con la descarga (se borró la copia mala)"
    FALLOS=$((FALLOS + 1)); DISTINTAS=$((DISTINTAS + 1)); continue
  fi
  printf '%s\t%s\n' "$H" "$FINAL" >> "$REGISTRO"

  DUR="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$FINAL" \
         | awk '{s=int($1+0.5); h=int(s/3600); m=int((s%3600)/60); if (h) printf "%d:%02d:%02d", h, m, s%60; else printf "%d:%02d", m, s%60}')"
  KBPS="$(ffprobe -v error -show_entries format=bit_rate -of csv=p=0 "$FINAL" | awk '{printf "%d", $1/1000}')"
  MB="$(awk -v b="$TAM" 'BEGIN {printf "%.1f", b/1e6}')"

  LINEA="OK  $(basename "$FINAL") | $DUR | $MB MB | $KBPS kbps"
  [ "$(basename "$FINAL" .mp3)" != "$TITULO" ] && LINEA="$LINEA | título original: $TITULO"
  [ -n "$AVISO" ] && LINEA="$LINEA | AVISO: $AVISO"
  [ -e "$SOMBRA" ] && LINEA="$LINEA | OJO: quedó $SOMBRA"
  echo "$LINEA"
  rm -f -- "${ORIGEN:?}"
done < <("${PY[@]}" bajar "$TMP" "${URLS[@]}")

# ---------------------------------------------------------------- verificación final
# Leer justo después de escribir puede devolver lo que quedó en la memoria del sistema y no lo
# que hay en la unidad: una tarjeta de capacidad falsa pasó así la primera verificación. Medido:
# 64 MiB salían idénticos sin desmontar y una tarjeta llena salía entera mal tras remontarla.
# Por eso, al final se desmonta, se monta de nuevo y se vuelve a comparar cada copia.
if [ -s "$REGISTRO" ]; then
  DEV="$(df -P "$DESTINO" | awk 'NR==2 {print $1}')"
  if [ "$(uname)" = "Darwin" ] && diskutil info "$DEV" 2>/dev/null | grep -qE 'Internal: +No|Removable Media: +Removable'; then
    MNT="$(diskutil info "$DEV" | sed -n 's/^ *Mount Point: *//p')"
    if diskutil unmount "$MNT" >/dev/null 2>&1 && diskutil mount "$DEV" >/dev/null 2>&1; then
      MNT2="$(diskutil info "$DEV" | sed -n 's/^ *Mount Point: *//p')"
      N=0; MALAS=0
      while IFS=$'\t' read -r H F; do
        N=$((N + 1)); F2="$MNT2${F#"$MNT"}"
        if [ ! -f "$F2" ] || [ "$(huella "$F2")" != "$H" ]; then
          echo "FALLÓ tras remontar: $(basename "$F2") (se borró la copia mala)"
          rm -f -- "${F2:?}"; MALAS=$((MALAS + 1))
        fi
      done < "$REGISTRO"
      FALLOS=$((FALLOS + MALAS)); DISTINTAS=$((DISTINTAS + MALAS))
      DESTINO="$MNT2${DESTINO#"$MNT"}"
      echo "Verificación final, con la unidad desmontada y montada de nuevo: $((N - MALAS)) de $N bien"
    else
      echo "AVISO: no pude desmontar la unidad para la verificación final (¿hay algo abierto en ella?)."
      echo "       Las copias se compararon recién escritas, y esa lectura puede venir de la memoria."
    fi
  else
    echo "Nota: las copias se compararon recién escritas, sin remontar la unidad; esa lectura puede"
    echo "      venir de la memoria del sistema."
  fi
fi

TOTAL="$(find "$DESTINO" -maxdepth 1 -type f -iname '*.mp3' ! -name '._*' | wc -l | tr -d ' ')"
SOMBRAS="$(find "$DESTINO" -maxdepth 1 -type f -name '._*' | wc -l | tr -d ' ')"
LIBRE_GB="$(df -Pk "$DESTINO" | awk 'NR==2 {printf "%.1f", $4/1024/1024}')"
echo "En el destino: $TOTAL mp3, $LIBRE_GB GB libres$([ "$SOMBRAS" -gt 0 ] && echo ", y $SOMBRAS archivos ._ ocultos (revisar)")"
if [ "$DISTINTAS" -gt 0 ]; then
  echo "AVISO: $DISTINTAS copia(s) no coincidieron con la descarga. La unidad está perdiendo"
  echo "       escrituras: revisa su sistema de archivos (diskutil verifyVolume) y prueba su capacidad"
  echo "       completa (F3: f3write/f3read) antes de guardar nada en ella."
fi
[ "$FALLOS" -eq 0 ]
