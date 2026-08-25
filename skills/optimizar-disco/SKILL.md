---
name: optimizar-disco
description: Diagnostica qué ocupa el disco de un Mac y genera un script de limpieza auditable con las rutas concretas, para que el usuario lo ejecute donde quiera. Usar cuando pidan "se me está llenando el disco", "libera espacio", "optimiza el almacenamiento", "qué está ocupando tanto", "no me queda espacio", o cuando algo falle por falta de espacio.
---

# Optimizar el disco de un Mac

Herramienta: `~/.claude/skills/optimizar-disco/diagnosticar-disco.py`
(ver su `README.md` para el diseño y los límites conocidos).

## El reparto de trabajo: tú diagnosticas, el usuario borra

El programa **nunca borra**: mide y emite un script de shell con las rutas literales. Tu trabajo es
correr el diagnóstico, interpretarlo, y entregarle el script. Tres razones:

1. Un borrado es irreversible y tú no sabes si esa carpeta de nombre opaco es el trabajo de la
   semana pasada.
2. Muchos repos tienen `Bash(rm -rf*)` en `deny` justamente para esto. **No lo esquives** con
   `find -delete`, `rm -r` sin `-f`, `unlink` ni un script intermedio: eludir el gate es peor que
   el problema que resuelve. Si te bloquea, dilo y entrega el comando.
3. El script generado es auditable línea por línea. Ese es el entregable, y su valor está en que
   una persona lo lea.

## Procedimiento

**1. Hora real y estado del disco.**

```bash
date '+%Y-%m-%d %H:%M:%S %Z'
df -h /System/Volumes/Data
```

**2. Diagnóstico y generación.** Tarda 2-3 minutos en un disco lleno, así que córrelo en background
y avisa que está corriendo:

```bash
python3 ~/.claude/skills/optimizar-disco/diagnosticar-disco.py \
  --generar ~/limpiar-disco-$(date +%Y%m%d).sh
```

Con `--json` obtienes la misma información estructurada, útil si vas a razonar sobre las cifras.

**3. Verifica los hallazgos grandes antes de recomendarlos.** El programa excluye solo las VMs, los
procesos vivos y los repos activos, pero no puede saber todo. Antes de decirle a alguien que borre
algo de varios GB, míralo:

- **¿Es un modelo de IA que sí ocupa?** Los de transcripción (Whisper, ASR) suelen alimentar
  herramientas propias del usuario. Pregunta, y agrégalo a `~/.optimizar-disco.conf` como
  `protegido:` para que no vuelva a aparecer nunca.
- **¿Es una carpeta de trabajo en curso?** Un nombre opaco en `Downloads` puede ser material de un
  cliente. Pregunta.
- **Antes de llamar "basura" a algo desconocido, búscalo:** un `grep -ril <término>` sobre sus repos
  cuesta segundos y evita hacerle explicar al usuario algo que ya está documentado en un repo.

**4. Reporta con cifras, no con adjetivos.** Un cuadro de qué ocupa cuánto, cuánto libera cada
bloque, y **qué no se va a tocar y por qué**. Esa última parte es la que genera confianza: muestra
que hubo verificación, no un borrado a ciegas.

**5. Entrega el script.** En Claude Code:

```
! bash ~/limpiar-disco-AAAAMMDD.sh
```

Y dile que puede leerlo, editarlo, correrlo en su terminal o pegarlo en otra IA para que lo revise.
Es texto plano sin dependencias.

**6. Verifica el resultado contra el disco.** No confíes en lo que reportó el script: corre `df -h`
de nuevo y comprueba que lo que debía preservarse siga ahí.

## Errores que ya se cometieron (no los repitas)

- **No edites un script mientras corre.** Bash lo lee por bloques guardando un offset de archivo;
  si cambia de longitud en caliente, el offset apunta a la mitad de otra línea y muere con un error
  de sintaxis en una línea que ya no existe. Pasó el 25/08/2026.
- **No confundas "mover" con "liberar".** Mover archivos dentro del mismo volumen no libera un solo
  byte. Si el usuario quiere ordenar para pasar cosas a un disco externo, dilo explícito.
- **No reportes espacio liberado sin medirlo con `df`.** Un `du` sobre un directorio recién borrado
  reporta lo que el sistema ya recreó vacío.
- **Dos archivos del mismo tamaño no son el mismo archivo.** Compara fechas antes de llamar
  duplicado a algo: un `.rar` más nuevo que el `.mp4` no es su origen, es otra descarga.
- **Una carpeta de 18 GB puede ser lo más importante del disco.** Antes de proponerla, `ls` su
  contenido: `vmlinuz` + `rootfs.img` es una máquina virtual activa, no caché.

## Después de limpiar

Si la limpieza fue significativa, deja el resultado en la nota de sesión del proyecto: cuánto se
liberó, de qué, qué se preservó y por qué, y qué quedó disponible para la próxima vez. Así la
próxima sesión no re-deriva el desglose del disco desde cero.

Y cuando el usuario diga "eso no lo toques", agrégalo a `~/.optimizar-disco.conf`, no solo lo
recuerdes en la conversación: ahí sobrevive a la sesión.
