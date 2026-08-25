# claude-skills

Skills para asistentes de IA de terminal (Claude Code y compatibles). Cada una resuelve una tarea
concreta que, hecha a mano, se repite igual todas las veces.

No son prompts sueltos: cada skill trae sus instrucciones, sus reglas duras aprendidas en uso real
y, cuando hace falta, la herramienta que ejecuta el trabajo.

## Las skills

### `optimizar-disco`
Mide qué ocupa el disco de un Mac y **genera el script de limpieza** con las rutas concretas que
encontró. Nunca borra: emite un `.sh` legible que ejecuta una persona.

Encuentra lo que los limpiadores de disco no miran: modelos de IA descargados hace un año,
`node_modules` de repos que no se tocan desde 2020, cachés de gestores de paquetes. Y **excluye
solo** lo que parece basura y no lo es: imágenes de VM (detecta `vmlinuz`, `rootfs.img`,
`Docker.raw`), rutas con un proceso vivo encima, repos con commits recientes.

Primer uso real: **59 GB liberados** en un Mac al 93% de ocupación, sin tocar los 18 GB que
parecían caché y eran la máquina virtual activa de una app.

### `analizar-chat-wsp`
Convierte un export de WhatsApp (`.zip`) en un dossier en markdown, **transcribiendo las notas de
voz localmente** con whisper.cpp (~7 s por audio, con caché) y dejando las imágenes listas para que
el asistente las lea con su visión nativa.

Sirve para preparar una reunión a partir de un chat, extraer compromisos o entender un hilo largo
sin leerlo completo. Incluye las reglas que evitan los errores típicos: una transcripción
automática no es un acta, y las fechas relativas ("mañana", "el jueves") se resuelven contra la
fecha del mensaje, no contra hoy.

### `grabar-demo`
Graba videos de demo de cualquier app web con Playwright, y los monta con `ffmpeg`: recorte del
marco del navegador, logos, fundidos, aceleración y música.

El recorrido se escribe como código, así que cuando la app cambia se vuelve a correr y el video
sale igual. Incluye un cursor dibujado (Playwright no graba el puntero), rótulos sobreimpresos y
perfiles de escritorio y móvil desde el mismo guion.

## Instalación

```bash
git clone <url-de-este-repo> && cd claude-skills
bash instalar.sh
```

Detecta los asistentes instalados en la máquina y crea symlinks, así que editar una skill aquí la
actualiza en todos a la vez. Destinos que reconoce: `~/.claude/skills`, `~/.agent/skills/skills`,
`~/.copilot/skills`, `~/.gemini/skills`, `~/.codex/skills`. Agrega otros con `--destino RUTA`.

```bash
bash instalar.sh --copiar      # copia en vez de symlink (otro equipo, un pendrive)
bash instalar.sh --verificar   # estado, sin tocar nada
bash instalar.sh --destino ~/mi-agente/skills
```

Reinicia el asistente después de instalar.

## Requisitos

- **macOS** para `optimizar-disco` (usa `df /System/Volumes/Data` y utilidades BSD).
- **Python 3.8+** para `optimizar-disco` y `analizar-chat-wsp`.
- **`ffmpeg`** para `grabar-demo` y para la transcripción de audios.
- **`whisper-cli`** (whisper.cpp) con un modelo en `~/.cache/whisper-models/` para transcribir.
- **`npx playwright install chromium`** para `grabar-demo`.

Cada skill dice en su `SKILL.md` qué necesita y qué hace si falta.

## Cómo está hecha una skill

Una carpeta con un `SKILL.md`: frontmatter con `name` y `description`, y debajo las instrucciones
en markdown. El asistente lee la descripción para decidir cuándo activarla, y ahí carga el resto.
Es texto plano, no un plugin compilado, así que la misma carpeta sirve en cualquier herramienta que
soporte el formato.

Lo que hace útil a una skill no es la descripción de la tarea, es lo que se aprendió haciéndola:
qué falla, qué hay que verificar antes, qué error ya se cometió. En estas skills eso está escrito
explícitamente, con el caso que lo originó.

## Licencia

MIT. Ver `LICENSE`.
