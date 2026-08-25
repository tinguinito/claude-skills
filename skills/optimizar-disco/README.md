# optimizar-disco

Mide qué ocupa el disco de un Mac de desarrollo y **genera el script de limpieza** con las rutas
que encontró. El diagnóstico es automático; el borrado lo corre una persona.

## Por qué están separados el diagnóstico y la limpieza

Medir es seguro y repetible. Borrar es irreversible y depende de contexto que ningún programa
tiene: si esa carpeta con nombre opaco es basura o el material de un cliente.

Así que `diagnosticar-disco.py` **nunca borra nada**. Lee, clasifica y emite un `.sh` con las rutas
literales que midió. Ese script:

- se lee completo en un minuto: cada línea dice qué borra, cuánto pesa, de qué fecha es y por qué
- se puede editar, comentar por bloques, o pegar en otra IA para que lo revise antes de correr
- no depende de este programa, de Python ni de ninguna configuración: es bash plano
- lleva en la cabecera **lo que se excluyó a propósito y por qué**, que es la parte que un borrado
  a ciegas se habría llevado
- pide confirmación escrita bloque por bloque, sin modo automático

Eso también resuelve un choque práctico: muchos agentes tienen `Bash(rm -rf*)` en `deny`. El agente
diagnostica y entrega el script; el humano lo ejecuta donde quiera.

## El problema que resuelve

Caso que originó la herramienta (25/08/2026, disco al 93%, 389 de 460 GB):

| Qué era | Cuánto | Por qué estaba ahí |
|---|---|---|
| Modelos de HuggingFace | 13.7 GB | descargados en may/2025 para una prueba |
| Modelos de Ollama | 11 GB | cuatro modelos, ninguno usado desde mar/2026 |
| Cachés de npm | 8.3 GB | `_cacache` + `_npx` |
| `node_modules` de repos inactivos | 5.7 GB | 19 carpetas, la más vieja de 2020 |
| Cachés de VS Code | 4.4 GB | instaladores de extensiones ya instaladas |

**59 GB liberados en una pasada**, y nada de eso lo detecta "Optimizar almacenamiento" de macOS,
que mira fotos, correo y papelera.

Pero el problema nunca fue borrar. En esa misma máquina había 18 GB en una carpeta que parecía
caché (`vm_bundles`) y era la máquina virtual activa de una app, y 1.5 GB de modelos que parecían
iguales a los otros y eran los que alimentaban las herramientas de transcripción del usuario. De
ahí las reglas de exclusión automática.

## Qué excluye solo, sin que se lo pidas

1. **Imágenes de VM y discos virtuales.** Si una carpeta contiene `vmlinuz`, `rootfs.img`,
   `Docker.raw`, `*.qcow2` o similares, queda fuera: es una VM en uso, no basura.
2. **Rutas con un proceso vivo usándolas.** Un `node_modules` con un server corriendo encima.
3. **Repos con commits recientes.** Los `node_modules` se juzgan por la actividad real del repo que
   los contiene, no por su nombre.
4. **Apps abiertas.** Vaciar el caché de VS Code abierto no sirve: lo reescribe al vuelo. Avisa y
   salta el bloque.
5. **Lo que esté en tu lista de protegidos**, que gana sobre todo lo anterior.

Y lo que creaste tú nunca se borra en automático: los videos grandes se **mueven**, avisando que
mover dentro del mismo volumen no libera un solo byte.

## Uso

```bash
cp optimizar-disco.conf.ejemplo ~/.optimizar-disco.conf
$EDITOR ~/.optimizar-disco.conf

python3 diagnosticar-disco.py                        # informe en pantalla
python3 diagnosticar-disco.py --generar limpiar.sh   # informe + script de limpieza
python3 diagnosticar-disco.py --json                 # salida estructurada, para un agente
python3 diagnosticar-disco.py --dias 90              # corte más agresivo
python3 diagnosticar-disco.py --raiz ~/proyectos     # dónde buscar node_modules (repetible)

bash limpiar.sh                                      # lo corres tú, tras leerlo
```

El diagnóstico tarda 2-3 minutos en un disco lleno: recorre el home con `du`.

## Límites conocidos

- **Solo macOS.** Usa `df /System/Volumes/Data` y utilidades BSD.
- **No hay "último uso" real.** macOS no mantiene `atime` confiable, así que se usa fecha de
  modificación. Un modelo que solo se leyó puede parecer viejo: para eso está la lista de
  protegidos.
- **Ollama no guarda fecha de uso**, solo de descarga del manifiesto. La herramienta lo dice
  explícitamente en la razón, en vez de fingir certeza.
- **Docker miente.** `prune` libera espacio dentro de `Docker.raw`, pero el archivo no se encoge.
  Se reporta como aviso, no como candidato.
- **Dos archivos del mismo tamaño no son el mismo archivo.** La herramienta no deduplica: no
  adivina que un `.rar` y un `.mp4` son la misma película.
