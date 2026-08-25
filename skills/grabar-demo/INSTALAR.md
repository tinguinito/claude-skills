# Instalar la skill `grabar-demo`

Graba videos de demo de cualquier app web con Playwright y los deja listos para enviar a un
cliente o publicar en redes. El recorrido queda escrito como código, así que se regraba
idéntico cuando la app cambia.

## Requisitos

- **Node 20 o superior** (`node -v`)
- **ffmpeg**: `brew install ffmpeg` en Mac, `apt install ffmpeg` en Linux
- Opcional, solo para verificar la música: **whisper.cpp** (`brew install whisper-cpp`) con un
  modelo en `~/.cache/whisper-models/` (por defecto busca `ggml-large-v3-turbo-q5_0.bin`; se
  puede apuntar a otro con la variable `WHISPER_MODELO`)

## Instalación

```bash
# 1. Descomprimir donde Claude Code busca las skills
mkdir -p ~/.claude/skills
unzip grabar-demo.zip -d ~/.claude/skills/

# 2. Instalar Playwright y su navegador (dentro de la carpeta de la skill)
cd ~/.claude/skills/grabar-demo
npm install
npx playwright install chromium
```

Listo. En la próxima sesión de Claude Code aparece como `/grabar-demo`, y también se puede
usar a mano con los scripts.

## Probar que quedó bien

```bash
cd /tmp
cat > prueba.mjs <<'EOF'
export const config = { nombre: 'prueba', url: 'https://example.com', perfil: 'escritorio' };
export default async function guion(page, u) {
  await u.rotulo('Funciona');
  await u.scroll(300);
}
EOF
node ~/.claude/skills/grabar-demo/scripts/grabar.mjs prueba.mjs --salida /tmp/grabaciones
~/.claude/skills/grabar-demo/scripts/montar.sh --in /tmp/grabaciones/prueba-escritorio.webm \
  --out /tmp/prueba.mp4
open /tmp/prueba.mp4
```

Si el archivo se reproduce y termina con el logo de cierre, está todo en su lugar.

## Cómo se usa en el día a día

1. Se escribe un guion en el repo del proyecto (`demos/<nombre>.mjs`), copiando
   `scripts/guion.ejemplo.mjs`.
2. Se graba: `node ~/.claude/skills/grabar-demo/scripts/grabar.mjs demos/<nombre>.mjs --salida grabaciones`
3. Se monta con `scripts/montar.sh` (logos, recorte, velocidad).
4. Si lleva música, se verifica la pista con `scripts/verificar-audio.sh` **antes** de
   montarla con `scripts/musicalizar.sh`.

El detalle completo, las utilidades del guion y las reglas del formato están en `SKILL.md`.

## Dos reglas que no conviene saltarse

1. **Nunca se ve el marco del navegador.** Grabando con `grabar.mjs` no puede pasar, porque
   Playwright captura solo el viewport. Si el material viene de una captura de pantalla del
   sistema, hay que recortar con `--crop`: una barra de URL con `localhost` en el video le
   dice al cliente que está viendo algo corriendo en el notebook de alguien.
2. **La pista musical se verifica antes de usarla**, aunque suene instrumental. Una pista
   sacada de otro video puede traer locución nombrando a otro cliente. Y si el video va a
   redes, hay que confirmar además la licencia.

## Personalizar la marca

El logo de cierre se busca en `assets/logo-cierre.png`. Pon ahí el tuyo, o pásalo con
archivo o se pasa `--logo-cierre /ruta/al/logo.png` en cada montaje.
