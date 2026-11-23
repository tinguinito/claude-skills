---
name: traer-de-youtube
description: Trae de YouTube lo que sirve para trabajar. La transcripción de un video o tutorial a un .md (con descripción, capítulos y minutos enlazados) para estudiarlo o implementar lo que enseña; capturas de pantalla en minutos dados para ver el código que se muestra; o el audio en MP3 a un pendrive o tarjeta SD, verificado. Usar cuando pasen un link de YouTube y pidan "transcribe este video", "qué dice este tutorial", "implementa lo de este video", "resume este video", "bájala en mp3", "pásala al pendrive", "música para el auto", o vayan mandando links uno tras otro.
---

# Traer de YouTube

Herramientas, en `~/.claude/skills/traer-de-youtube/`:

- `traer.py`: `transcribir`, `capturas`, `info`, `destinos`, `bajar`. Ayuda: `traer.py -h`.
- `audio-a-pendrive.sh`: baja MP3 y los copia verificados a una unidad externa.

Requieren `yt-dlp`, `ffmpeg` y, para los desafíos JS que hoy pone YouTube, `deno`. La
transcripción local usa `whisper-cli` (whisper.cpp) y un modelo ggml en `~/.cache/whisper-models`.
Corre los `.py` con `python3 -I`.

Primero, siempre: **`traer.py info URL`**. Dice duración, capítulos y qué subtítulos hay, y con eso
decides el camino sin bajar nada.

## A. Un video o tutorial para estudiarlo o implementarlo

**1. Transcribir al proyecto que corresponde.**

```bash
python3 -I ~/.claude/skills/traer-de-youtube/traer.py transcribir "URL" --salida <docs del proyecto>/youtube
```

El `.md` queda en el repo dueño del tema, no en `/tmp`: es el respaldo de dónde salió lo que se
implementó. Trae metadatos, la **descripción completa** (ahí suelen estar el repo, los comandos y
las versiones), los capítulos y la transcripción en párrafos de ~45 s, cada uno con su minuto
enlazado. Usa subtítulos manuales si existen, si no los automáticos del idioma original, y si no
hay ninguno transcribe en local con whisper (`--whisper` lo fuerza). Imprime la ruta.

**2. Léelo entero con `Read`.** No trabajes con un resumen. Si es muy largo (un curso de 5 horas),
lee los capítulos y luego los tramos que importan para lo que se pidió, y di qué tramos no leíste.

**3. Lo que se ve y no se dice va por capturas.** La transcripción no trae el código, la
configuración ni la pantalla que se muestran. Elige los minutos con los capítulos o la
transcripción ("acá ven el archivo de configuración...") y léelas con `Read`:

```bash
python3 -I ~/.claude/skills/traer-de-youtube/traer.py capturas "URL" --en 10:30,16:20 --salida <carpeta>
```

`--cada SEG` saca una cada N segundos, con un tope de 40 por llamada: cada imagen cuesta contexto.

**4. Antes de implementar, contrasta.**

- **Repo enlazado en la descripción:** el código sale de ahí, no se reconstruye desde lo que se
  oyó.
- **Comandos, nombres de paquetes y flags:** los subtítulos automáticos y whisper los escuchan
  mal (en las pruebas, "EDteam" salió como "de team"). Confírmalos con la captura, el repo o la
  documentación.
- **La fecha del video está en el `.md`.** Un tutorial de hace dos años puede usar versiones o APIs
  que ya cambiaron: revisa la documentación vigente antes de copiar.
- Al reportar, separa lo que dice el video de lo que tú infieres o completas.

**5. Implementa con las reglas del proyecto activo** (ramas, PR, pruebas). El video es una fuente,
no una autorización para saltárselas.

## B. Audio a un pendrive o tarjeta SD

**1. Ubica la unidad y mira qué tiene.**

```bash
bash ~/.claude/skills/traer-de-youtube/audio-a-pendrive.sh --listar-destinos
```

- Si hay una sola, esa es. Si hay más de una, **pregunta** cuál: no adivines por el nombre.
- Mira qué tiene adentro (`ls -la`) antes de escribir. "La tarjeta vacía" puede no estarlo: si trae
  contenido, no lo toques, deja la música en una carpeta propia (`--destino "/Volumes/X/Musica"`;
  el script la crea) y cuéntale al usuario lo que viste.
- Nunca escribas en el disco interno ni en una unidad que el usuario no nombró.

**2. Baja y copia.** Pasa los links tal como llegan: el script deja solo el `v=`. Un link copiado
desde una "Mix" trae `&list=RD...`, y sin limpiar se bajarían decenas de canciones.

```bash
bash ~/.claude/skills/traer-de-youtube/audio-a-pendrive.sh [--destino RUTA] "URL1" "URL2" ...
```

Por cada link imprime `OK archivo | duración | MB | kbps`, el título original si el nombre cambió,
y un AVISO si es una pista larga. Un `&t=1108s` en el link suele significar que el usuario quería
una canción dentro de un concierto o una selección: dile que bajó el video completo y ofrece
partirlo (con capítulos, `yt-dlp --split-chapters`; sin capítulos hay que encontrar los cortes).

Si el usuario va mandando links de a uno, procésalos en orden con el mismo destino. No esperes a
que termine.

**3. Revisa los nombres.** El script quita lo mecánico ("(Official Video)", emojis, caracteres que
FAT32 no acepta). Lo editorial te toca a ti: títulos promocionales largos → algo corto; orden
invertido ("Canción - Artista") → "Artista - Canción"; TODO EN MAYÚSCULAS → normal. Renombra con
`mv` **desde bash**, no desde Python (regla 1).

**4. Reporta** en una tabla: archivo y duración, cuántas canciones quedan y el espacio libre, qué
nombres cambiaste y qué pistas son largas. Ofrece expulsar la unidad (`diskutil eject`), pero no la
expulses sin que te lo pidan: pueden venir más links.

## Reglas duras (cada una salió de un caso real)

1. **La copia al pendrive se hace desde bash, nunca desde Python.** Medido en macOS 27: todo
   archivo creado por un proceso que desciende de Python (`shutil.copyfile`, `open`/`write`,
   `os.mkdir`, e incluso un `cp -X` lanzado con `subprocess`) recibe `com.apple.provenance`. En
   FAT32 eso deja un `._nombre.mp3` oculto por canción, y muchas radios de auto los listan como
   pistas rotas. El mismo `cp -X` desde bash no lo deja. Si aparece un `._`, `xattr -c archivo`
   (desde bash) lo elimina.
2. **Baja a una carpeta temporal del disco interno**, no directo al pendrive: así no quedan `.part`,
   `.webm` ni miniaturas a medio escribir en la unidad si algo falla.
3. **Verifica cada copia con MD5, y la verificación que vale es la que lee de la unidad.** Leer
   justo después de escribir puede devolver lo que quedó en la memoria del sistema. Por eso el
   script, al terminar, desmonta la unidad, la monta de nuevo y vuelve a comparar todo. Caso real,
   una tarjeta SD de 4 GB de un teléfono viejo:
   - Aceptó 13 canciones sin dar ningún error y devolvió otra cosa al leerlas.
   - `diskutil verifyVolume` encontró la FAT corrupta (clústeres fuera de rango, huérfanos).
     `repairVolume` la dejó "sana" según fsck, y las escrituras seguían fallando.
   - Después de formatearla, 64 MiB salían idénticos, pero llenarla entera y releerla tras remontar
     dio 14 de 14 piezas de 256 MiB distintas. Con la música, las primeras ~88 MB quedaron bien y
     de ahí en adelante falló todo. La FAT corrupta era un síntoma, no la causa.

   Una prueba corta no declara sana a una unidad: hay que probar la capacidad completa (escribir,
   desmontar, montar y comparar; F3 con `f3write`/`f3read` lo hace). Y no formatees sin permiso
   explícito del usuario: borra todo lo que tenga.
4. **Si yt-dlp falla con "Sign in", 403 o "challenge", casi siempre está desactualizado.**
   Actualízalo y reintenta. Revisa que `deno` esté instalado.
5. **Whisper inventa sobre el silencio.** Si el audio es mudo (grabación de pantalla sin voz),
   `transcribir` no lo pasa por whisper y lo dice en el `.md`. Ahí el camino es `capturas`.
6. **Es para uso personal y de estudio.** No redistribuyas lo que bajes.

## Límites conocidos

- La detección de unidades usa `diskutil` en macOS y `/media`/`/run/media` en Linux. En Windows,
  pasa `--destino`.
- No parte recopilaciones sin capítulos.
- El MP3 sale de lo que entrega YouTube (normalmente Opus de ~130-160 kbps) recodificado en VBR de
  máxima calidad: un archivo de 280 kbps no suena mejor que su fuente.
- Videos con restricción de edad o privados necesitan cookies del navegador
  (`yt-dlp --cookies-from-browser`), que la skill no maneja.
