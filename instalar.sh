#!/usr/bin/env bash
# Instala estas skills en los asistentes de IA que tengas en la máquina.
#
# QUÉ ES UNA SKILL Y POR QUÉ ESTO FUNCIONA EN VARIOS ASISTENTES
#   Una skill es una carpeta con un SKILL.md: frontmatter (`name`, `description`) y, debajo, las
#   instrucciones en markdown. El asistente lee la descripción para decidir cuándo activarla, y
#   entonces carga el resto. Es texto plano, no un plugin compilado, así que la misma carpeta
#   sirve para cualquier herramienta que soporte el formato.
#
# DESTINOS QUE DETECTA
#   ~/.claude/skills        Claude Code / Claude Desktop
#   ~/.agent/skills/skills  agentes compatibles con el formato antigravity
#   ~/.copilot/skills       GitHub Copilot CLI
#   ~/.gemini/skills        Gemini CLI
#   ~/.codex/skills         Codex CLI
#   Agrega los que quieras con --destino RUTA (repetible).
#
# USO
#   bash instalar.sh                    # detecta destinos, pregunta y symlinkea
#   bash instalar.sh --copiar           # copia en vez de symlink (para otro equipo o un pendrive)
#   bash instalar.sh --destino ~/x/skills
#   bash instalar.sh --verificar        # muestra el estado, no toca nada
#   bash instalar.sh --si               # no pregunta (para scripts)
#
# SYMLINK O COPIA
#   Symlink (default): editas la skill en el repo y se actualiza en todos los asistentes a la vez.
#   Copia: independiente del repo, útil si el repo no va a vivir en esa máquina. Se desincroniza,
#   así que hay que reinstalar tras cada `git pull`.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODO="symlink"; PREGUNTAR="si"; VERIFICAR="no"; DESTINOS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --copiar)    MODO="copia"; shift ;;
    --verificar) VERIFICAR="si"; shift ;;
    --si)        PREGUNTAR="no"; shift ;;
    --destino)   DESTINOS+=("$2"); shift 2 ;;
    -h|--help)   sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción desconocida: $1"; exit 1 ;;
  esac
done

if [ "${#DESTINOS[@]}" -eq 0 ]; then
  for d in "$HOME/.claude/skills" "$HOME/.agent/skills/skills" "$HOME/.copilot/skills" \
           "$HOME/.gemini/skills" "$HOME/.codex/skills"; do
    [ -d "$d" ] && DESTINOS+=("$d")
  done
fi

if [ "${#DESTINOS[@]}" -eq 0 ]; then
  echo "No encontré ningún directorio de skills conocido."
  echo "Pasa uno con --destino RUTA (se crea si no existe)."
  exit 1
fi

SKILLS=()
for s in "$REPO"/skills/*/; do
  [ -f "${s}SKILL.md" ] && SKILLS+=("${s%/}")
done
[ "${#SKILLS[@]}" -eq 0 ] && { echo "No hay skills en $REPO/skills"; exit 1; }

echo "Skills a instalar (${#SKILLS[@]}):"
for s in "${SKILLS[@]}"; do
  # el nombre real es el del frontmatter; el del directorio es solo una pista
  nombre="$(sed -n 's/^name: *//p' "$s/SKILL.md" | head -1)"
  echo "  - ${nombre:-$(basename "$s")}"
done
echo
echo "Destinos detectados (${#DESTINOS[@]}):"
for d in "${DESTINOS[@]}"; do echo "  - $d"; done

if [ "$VERIFICAR" = "si" ]; then
  echo
  for d in "${DESTINOS[@]}"; do
    echo "== $d"
    for s in "${SKILLS[@]}"; do
      n="$(basename "$s")"; t="$d/$n"
      if [ -L "$t" ]; then
        [ "$(readlink "$t")" = "$s" ] && echo "  ok        $n" || echo "  otro link $n -> $(readlink "$t")"
      elif [ -d "$t" ]; then echo "  copia     $n"
      else echo "  falta     $n"; fi
    done
  done
  exit 0
fi

if [ "$PREGUNTAR" = "si" ]; then
  printf '\nInstalar por %s en esos %d destino(s)? [s/N] ' "$MODO" "${#DESTINOS[@]}"
  read -r r
  case "$r" in s|S|si|SI|y|Y) ;; *) echo "Cancelado."; exit 0 ;; esac
fi

for d in "${DESTINOS[@]}"; do
  mkdir -p "$d" || { echo "No pude crear $d"; continue; }
  echo
  echo "== $d"
  for s in "${SKILLS[@]}"; do
    n="$(basename "$s")"; t="$d/$n"
    # un directorio real que no pusimos nosotros no se borra: se respalda FUERA del árbol de
    # skills, o el asistente lo cargaría como una skill duplicada
    if [ -L "$t" ]; then
      rm "$t"
    elif [ -e "$t" ]; then
      resp="$HOME/.skills-respaldos/$(basename "$d")-$n-$(date +%Y%m%d%H%M%S)"
      mkdir -p "$(dirname "$resp")"
      mv "$t" "$resp" && echo "  respaldé lo que había en: $resp"
    fi
    if [ "$MODO" = "symlink" ]; then
      ln -s "$s" "$t" && echo "  symlink   $n"
    else
      cp -R "$s" "$t" && echo "  copia     $n"
    fi
  done
done

echo
echo "Listo. Reinicia el asistente para que detecte las skills nuevas."
[ "$MODO" = "copia" ] && echo "Instalaste por COPIA: repite esto después de cada 'git pull'."
