---
name: grabar-demo
description: Graba videos de demo de cualquier proyecto (web) con Playwright y los deja listos para enviar a un cliente o publicar en redes. El recorrido queda en código, así que se regraba idéntico cuando la app cambia. Incluye montaje con ffmpeg (recorte del marco del navegador, logos de entrada y cierre, aceleración) y musicalización con verificación previa de la pista. Usar cuando pidan "graba un demo", "video de la plataforma", "un extracto para redes", "el dulce para el cliente", o /grabar-demo.
---

# Grabar demos de producto

Convierte cualquier app web en un video de demo reproducible. Sirve para adjuntar a una
propuesta, para pedir una reunión de cierre y como material de redes.

**Principio:** el recorrido se escribe como código (un *guion* de Playwright que vive en el
repo del proyecto). Cuando la app cambia, se vuelve a correr y el video sale igual, sin
volver a grabar a mano.

## Flujo

1. **Guion** — copiar `scripts/guion.ejemplo.mjs` a `<repo-del-proyecto>/demos/<nombre>.mjs`
   y escribir el recorrido con las utilidades de abajo.
2. **Grabar** — `node <skill>/scripts/grabar.mjs demos/<nombre>.mjs --salida grabaciones`
   Deja un `.webm` del tamaño exacto del viewport.
3. **Montar** — `scripts/montar.sh` agrega logos, fundidos y aceleración, y entrega `.mp4`.
4. **Música** — `scripts/verificar-audio.sh` sobre la pista, y recién después
   `scripts/musicalizar.sh`.
5. **Entregar** — mandar el archivo por `SendUserFile` **y** decir en el chat qué muestra,
   cuánto dura y en qué formato quedó.

## Reglas que no se saltan

**1. Nunca se ve el marco del navegador.** Ni bordes de ventana, ni pestañas, ni barra de
URL. Si aparece `localhost:5173`, el video comunica "esto corre en el notebook de alguien",
no "esto es un producto". Grabando con `grabar.mjs` el problema no existe: Playwright captura
solo el viewport. Si por alguna razón el material viene de una captura de pantalla del
sistema, es **obligatorio** recortar con `--crop W:H:X:Y`, y verificar el recorte extrayendo
un frame antes de montar el video completo:
`ffmpeg -ss 5 -i entrada.mov -vf "crop=W:H:X:Y" -frames:v 1 check.png`

**2. La pista musical se verifica antes de usarla.** Correr `verificar-audio.sh <pista>`
siempre, aunque suene instrumental. En un caso real la pista candidata venía de un video de
otro cliente: si hubiera traído locución, el demo habría nombrado a la empresa equivocada. Una
transcripción que devuelve frases inconexas o los típicos "Subtítulos por..." indica audio
sin voz; texto coherente y repetido indica que hay locución y la pista se descarta.
Si el video va a **redes**, confirmar además la **licencia** de la pista: una pista reutilizada
de otro material propio no equivale a una licencia para publicar.

**3. El audio original de la app no va.** `montar.sh` descarta la pista de audio de entrada
(`-an`). Si hace falta locución, se graba aparte y se monta explícitamente.

**4. Verificar el resultado antes de entregarlo.** Extraer 3 o 4 frames del `.mp4` final y
mirarlos (`ffmpeg -ss N -i final.mp4 -frames:v 1 f.jpg`). Un video que sale con franjas,
proporción rara o el logo cortado se detecta en 20 segundos y no después, en el correo del
cliente. Ojo: un frame que se ve "con franjas" en una vista previa a veces es solo el visor;
comparar contra las dimensiones reales (`ffprobe`).

## Utilidades del guion

El guion recibe `(page, u)`. `page` es la página de Playwright; `u` agrega ritmo de demo:

| Utilidad | Para qué |
|---|---|
| `u.pausa(ms)` | dar tiempo de lectura |
| `u.mover(selector \| {x,y})` | mover el cursor visible en curva suave |
| `u.click(selector)` | mover, pulsar con destello y hacer clic |
| `u.escribir(selector, texto)` | tecleo con ritmo humano |
| `u.scroll(px \| selector)` | scroll suave |
| `u.esperar(selector)` | esperar a que algo aparezca |
| `u.rotulo(texto)` | rótulo sobreimpreso que nombra lo que se muestra |
| `u.ocultarTexto('aviso', …)` | esconder banners del entorno de prueba |
| `u.css(reglas)` | inyectar CSS en la página |

El cursor no existe en una grabación de Playwright, por eso se dibuja uno: sin él, el video
muestra cosas que cambian sin causa visible.

## Comandos

```bash
SKILL=~/.claude/skills/grabar-demo

# Grabar (escritorio y móvil son dos pasadas del mismo guion)
node $SKILL/scripts/grabar.mjs demos/panel.mjs --salida grabaciones
node $SKILL/scripts/grabar.mjs demos/panel.mjs --salida grabaciones --perfil movil
#   --headed  para verlo correr mientras se ajusta el guion

# Montar: logo del cliente al inicio, el propio al cierre, 1,6x
$SKILL/scripts/montar.sh --in grabaciones/panel-escritorio.webm --out demo-escritorio.mp4 \
  --speed 1.6 --logo-intro assets/logo-cliente.png

# Música (verificar primero)
$SKILL/scripts/verificar-audio.sh musica.m4a
$SKILL/scripts/musicalizar.sh demo-escritorio.mp4 demo-final.mp4 musica.m4a 0.32
```

`montar.sh` acepta además `--crop W:H:X:Y`, `--desde SEG`, `--hasta SEG`, `--logo-cierre`,
`--sin-cierre`, `--ancho-intro`, `--ancho-cierre`, `--dur-logo`, `--fondo`, `--fps`.

`--desde` es el que más se usa: casi todo guion empieza con un login o una carga que no
debe salir en el video. Se graba completo y se recorta en el montaje.

## Cuando la app necesita servicios locales

Un demo de una app con backend necesita el entorno arriba, y ahí aparecen dos problemas que
la skill ya resuelve:

- **Puertos ocupados por otro proyecto.** `config.redirigir = { 'localhost:9099':
  '127.0.0.1:9098' }` manda las llamadas de la página a otro puerto. Sirvió para levantar un
  emulador de Firebase propio cuando otro proyecto tenía tomado el habitual, sin tocar la
  sesión ajena. Vale para cualquier servicio, no solo Firebase.
- **Datos de prueba que ensucian la pantalla.** Productos "QA", categorías "test", avisos de
  suscripción vencida. Lo cosmético (banners de estado del entorno) se tapa con
  `u.ocultarTexto()`; lo que es basura en los datos conviene limpiarlo en la base de
  desarrollo antes de grabar, no maquillarlo. Regla: **maquillar el entorno sí, maquillar el
  producto no** — si el video muestra algo que la app no hace, deja de ser un demo.

Y avisa siempre a quien va a usar el video de qué se ocultó: es información que él necesita
para responder cuando el cliente pregunte.

## Escritorio y móvil

`--perfil movil` en la línea de comandos manda sobre el `viewport` del guion, así que el
mismo archivo se graba en los dos formatos. Lo que **no** se traslada solo es el recorrido:
un layout móvil esconde el menú lateral y los selectores del guion de escritorio dejan de
tener caja visible (el grabador falla con "No se encontró el elemento…" y guarda igual lo
grabado hasta ahí). Para móvil conviene un guion propio, corto, con los selectores de la
barra inferior.

## Formatos

- **Escritorio / correo a cliente:** viewport 1600×1000 (o el del mock), 1,5x–1,7x de
  velocidad, entre 1 y 2 minutos. Más largo que eso no se ve completo.
- **Móvil / redes:** perfil `movil` (500×990, vertical), 15 a 30 segundos, un solo mensaje.
- Salida siempre H.264 `yuv420p` con `+faststart`: reproduce en cualquier cliente de correo
  y en el teléfono.

## Requisitos

`npx playwright install chromium`, `ffmpeg` y, para la
verificación de audio, `whisper-cli` con el modelo en `~/.cache/whisper-models/`
(configurable con `WHISPER_MODELO`).

## Precedente

Primer uso real: dos videos del mock de una plataforma enviados a un cliente (escritorio
1552×992 a 1,6x, y móvil 500×990 de 18 s). Ahí se aprendieron las dos reglas duras de arriba:
recortar el marco del navegador y verificar la pista antes de usarla.
