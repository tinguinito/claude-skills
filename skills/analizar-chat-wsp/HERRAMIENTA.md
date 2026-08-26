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
curl -L -o ggml-large-v3-q5_0.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-q5_0.bin?download=true"
```

Nada más: no hay entorno virtual, no hay dependencias de Python (solo la librería
estándar), no hay API key, no hay cuenta que configurar.

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
- **Los videos se transcriben igual que los audios.** ffmpeg extrae la pista de audio de un
  `.mp4` con el mismo comando que usa para un `.opus`, así que no hay dos rutas de código. En el
  dossier salen con 🎬 en vez de 🎙️, para que se sepa que la fuente era un video. Un video de
  varios minutos tarda bastante más que una nota de voz: `--sin-video` los salta.
- **Los documentos no se leen, se listan con su ruta absoluta** en una sección propia, igual que
  las imágenes. El agente abre PDF, docx y planillas de forma nativa: interpretarlos en el script
  sería reimplementar lo que ya sabe hacer. Una cotización adjunta suele traer el dato duro que el
  texto del chat no dice.
- Formatos de export soportados: **iOS** (`[DD-MM-YY, HH:MM:SS] Autor:`) y **Android**
  (`DD/MM/YYYY, HH:MM - Autor:`). El detectado se declara en la cabecera del dossier —
  si dice `desconocido`, el parseo falló y hay que revisar el `.txt`.
- El export de WhatsApp **trunca los chats muy largos**; es límite de WhatsApp, no del
  script.

## Relación con el puente WhatsApp (P4)

Esto es la **vía manual** (flujo C de `docs/referencia/p4-puente-whatsapp.md`):
disponible hoy, cero riesgo, cero costo. No reemplaza a P4 (número secundario + Cloud
API oficial, donde el audio llega solo al reenviarlo). Al contrario: cuando P4 se
implemente, **el transcriptor ya está resuelto y se reutiliza tal cual** — el webhook
solo tendrá que llamar a `transcribir()`.
