# wsp-dossier — export de WhatsApp → dossier legible, sin API ni costo

Resuelve el ciclo manual que hay que repetir cada vez que hace falta analizar un
chat de WhatsApp con audios: exportar → transcribir cada nota de voz a mano en Notas de
Apple → pegar la transcripción al agente. Ahora es **un comando**.

## Qué hace

Toma el `.zip` que produce WhatsApp (*Exportar chat → Adjuntar archivos*) y escribe un
único `.md` con:

- La conversación completa linealizada por fecha.
- **Cada nota de voz reemplazada por su transcripción inline**, en el lugar exacto donde
  fue enviada — así el hilo se lee de corrido, sin saltar entre archivos.
- Las imágenes listadas con su ruta absoluta, para que el agente las lea con el tool
  `Read` (ver "Por qué las imágenes no las procesa el script").
- Un resumen de cabecera: participantes, conteo por tipo de adjunto, rango de fechas.

## Requisitos (instalación única)

```bash
brew install whisper-cpp ffmpeg
mkdir -p ~/.cache/whisper-models && cd ~/.cache/whisper-models
# El modelo POR DEFECTO del script. Si falta este, no arranca.
curl -L -o ggml-large-v3-turbo-q5_0.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin?download=true"
# Opcional, solo para audio largo y limpio (reuniones): --modelo large-v3-q5_0
curl -L -o ggml-large-v3-q5_0.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin?download=true"
```

Nada más: no hay entorno virtual, no hay dependencias de Python (solo la librería
estándar), no hay API key, no hay cuenta que configurar.

La única excepción es `voces.py` (separación de hablantes), que necesita `uv` (`brew install uv`)
y se arma solo su entorno en `~/.cache/wsp-voces/` la primera vez (unos 100 MB entre
sherpa-onnx y dos modelos). Ver "Separación de hablantes" más abajo.

## Uso

```bash
python3 herramientas/wsp-dossier/wsp_dossier.py "~/Downloads/WhatsApp Chat - Nombre.zip"
```

Imprime la ruta del `.md` generado. Opciones útiles:

| Flag | Para qué |
|---|---|
| `-o RUTA.md` | dónde escribir el dossier (default: junto al zip) |
| `--sin-audio` | solo texto y listado de adjuntos, sin transcribir (rápido, para hojear) |
| `-m medium` | modelo más liviano si el largo va lento |
| `-l en` | idioma del audio distinto del español |
| `--json X.json` | además, volcar los mensajes estructurados |

Acepta también una **carpeta ya extraída** en vez del zip.

## Decisiones de diseño (y su por qué)

**Transcripción local, no API.** `whisper.cpp` con `large-v3-turbo-q5_0` (547 MB) corre por defecto: comparado el 17/08/2026 contra `large-v3-q5_0` en 35 audios reales de WhatsApp, el turbo resultó igual o mejor (el large pierde puntuación y garblea notas de voz comprimidas). Para audio largo y limpio (reuniones) usar `--modelo large-v3-q5_0` (ya descargado). El default
sobre Metal en Apple Silicon. Medido con un chat real: **9 audios en 68
segundos**. Costo $0 y —lo que decide el asunto— el contenido privado de clientes y
socios **nunca sale del Mac**. Se evaluó el free tier de Gemini: es gratis, pero implica
subir audio ajeno a un tercero y aceptar rate limits; no compensa.

**Por qué las imágenes no las procesa el script.** El agente (Claude) tiene visión
nativa: lee un `.jpg` directamente con el tool `Read`. Montar un modelo de visión local
o llamar a una API para describir imágenes sería pagar por una capacidad que ya está
disponible gratis. El script solo las localiza y lista su ruta.

**Caché por hash de contenido.** Las transcripciones se guardan en
`~/.cache/wsp-dossier/` indexadas por SHA del audio + modelo + idioma. Re-correr el
mismo export es instantáneo, y un audio reenviado en otro chat tampoco se re-transcribe.

**Un solo archivo, stdlib pura.** Sin `requirements.txt` ni venv que se rompa en seis
meses. El costo de mantención tiende a cero.

## Límites conocidos

- **La transcripción es automática.** Es buena, pero no es un acta. Antes de usar una
  cita literal como prueba (un precio, un compromiso, una cifra), escucha el audio.
  El dossier lleva ese aviso impreso en la cabecera.
- **Los videos CON voz se transcriben igual que los audios.** ffmpeg extrae la pista de audio de
  un `.mp4` con el mismo comando que usa para un `.opus`, así que no hay dos rutas de código. En el
  dossier salen con 🎬 en vez de 🎙️, para que se sepa que la fuente era un video. Un video de
  varios minutos tarda bastante más que una nota de voz: `--sin-video` los salta.

- **Los videos MUDOS no se transcriben: se miran.** Antes de transcribir, el script mide el
  volumen medio con `volumedetect`; bajo −60 dB (o sin pista de audio) considera que el video no
  tiene narración, y en vez de pasarlo por whisper extrae una rejilla de fotogramas que el agente
  lee con `Read`, igual que una imagen.

  El motivo es que **whisper alucina sobre el silencio**, y con seguridad: devuelve frases como
  "Gracias por ver el video" o el crédito de una productora de subtítulos. Eso es peor que no
  transcribir, porque el dossier queda con texto plausible que nadie pone en duda, tapando lo que
  el video sí mostraba. Caso real (26-08-2026, chat de una operadora en terreno): de cuatro
  videos, tres eran grabaciones de pantalla mudas a −90 dB; el que contenía la prueba visual del
  bug que se estaba investigando quedó transcrito como *"CC por Antarctica Films Argentina"*.
  Una grabación de pantalla muda suele ser **la mejor evidencia del chat**, porque muestra el
  error tal como ocurrió.
- **Los documentos no se leen, se listan con su ruta absoluta** en una sección propia, igual que
  las imágenes. El agente abre PDF, docx y planillas de forma nativa: interpretarlos en el script
  sería reimplementar lo que ya sabe hacer. Una cotización adjunta suele traer el dato duro que el
  texto del chat no dice.
- Formatos de export soportados: **iOS** (`[DD-MM-YY, HH:MM:SS] Autor:`) y **Android**
  (`DD/MM/YYYY, HH:MM - Autor:`). El detectado se declara en la cabecera del dossier —
  si dice `desconocido`, el parseo falló y hay que revisar el `.txt`.
- El export de WhatsApp **trunca los chats muy largos**; es límite de WhatsApp, no del
  script.

## Separación de hablantes (`voces.py`)

`wsp_dossier.py` no separa voces porque en un export de WhatsApp no hace falta: cada nota de
voz ya viene firmada por quien la mandó. El caso distinto es una **grabación de reunión**
(Notas de Voz de Apple, un m4a de 10 minutos con 2 o 3 personas y a veces alguien más de fondo).
Ahí `voces.py` transcribe con el mismo whisper.cpp y, encima, agrupa por hablante.

```bash
python3 voces.py grabacion.m4a -n 3            # fijar la cantidad de personas
python3 voces.py grabacion.m4a                 # automático, umbral 0.9 (-t para ajustar)
```

**Cómo lo hace, y por qué así.** Se evaluaron tres vías el 10/10/2026:

- `whisper-cli --diarize` solo sirve para audio estéreo con una persona por canal, y
  `--tinydiarize` marca cambios de turno sin decir quién habla y solo tiene modelo en inglés.
  Descartadas.
- pyannote.audio con WhisperX es el estándar, pero exige cuenta en Hugging Face, aceptar
  condiciones de dos modelos y bajar torch (varios GB). Descartada por fricción, no por calidad.
- **sherpa-onnx** trae el mismo modelo de segmentación de pyannote 3.0 convertido a ONNX, de
  descarga libre desde GitHub, más una huella de voz CAM++ de 3D-Speaker (28 MB). Sin cuenta ni
  token, y el audio no sale del Mac. Es lo que usa `voces.py`.

Medido con una reunión real de 8 min 46 s en un M1 Pro: 1 min 24 s de diarización más la
transcripción habitual. Con 3 voces fijadas, el reparto fue consistente de principio a fin y
aisló los 16 segundos de un menor que interrumpió la conversación.

**Límites.**

- **Fijar `-n` casi siempre.** En automático el agrupamiento tiende a partir una misma voz en
  varias: la misma grabación dio 38 voces con umbral 0,5 y 7 con umbral 1,0. Si no se sabe
  cuántas personas había, probar 2 y 3 y mirar cuál calza.
- **Distingue voces, no las reconoce.** H0, H1 y H2 son etiquetas. El nombre lo infiere el agente
  por el contenido y lo deja marcado como inferido en la nota.
- **Los bordes entre turnos son dudosos.** Una frase corta dicha justo al cambiar de hablante
  (un "sí", un "10 de 10") puede caer en la voz equivocada. Lo que comprometa se confirma escuchando.
- `-ml 1 -sow` corta por palabra, no por token, para que un cambio de voz no parta una palabra
  por la mitad.

## Relación con el puente WhatsApp (P4)

Esto es la **vía manual** (flujo C de `docs/referencia/p4-puente-whatsapp.md`):
disponible hoy, cero riesgo, cero costo. No reemplaza a P4 (número secundario + Cloud
API oficial, donde el audio llega solo al reenviarlo). Al contrario: cuando P4 se
implemente, **el transcriptor ya está resuelto y se reutiliza tal cual** — el webhook
solo tendrá que llamar a `transcribir()`.
