#!/usr/bin/env python3
"""
diagnosticar-disco.py — mide qué ocupa el disco de un Mac y GENERA el script de limpieza.

POR QUÉ ESTÁN SEPARADOS EL DIAGNÓSTICO Y LA LIMPIEZA
    Medir es seguro y se puede automatizar; borrar es irreversible y no. Este programa NUNCA
    borra nada: solo lee, clasifica y emite un script de shell con las rutas literales que
    encontró. Ese script lo audita y lo corre una persona, en la terminal que quiera, sin
    depender de este programa ni de ninguna configuración.

    El script generado es texto plano legible: cada línea dice qué borra, cuánto pesa, de qué
    fecha es y por qué se considera prescindible. Se puede leer completo en un minuto, pegar en
    otra IA para que lo revise, o editar antes de correr.

USO
    python3 diagnosticar-disco.py                      # informe en pantalla
    python3 diagnosticar-disco.py --generar limpiar.sh # informe + script de limpieza
    python3 diagnosticar-disco.py --json               # salida estructurada (para un agente)
    python3 diagnosticar-disco.py --dias 90            # corte de inactividad (default 180)
    python3 diagnosticar-disco.py --raiz ~/proyectos   # dónde buscar node_modules (repetible)

CONFIG (opcional): ~/.optimizar-disco.conf, una directiva por línea
    dias: 180
    raiz: ~/proyectos
    protegido: ~/.cache/whisper-models
    protegido: ~/Library/Caches/ms-playwright

REQUISITOS
    macOS y Python 3.8+. Usa `df /System/Volumes/Data` y fechas de mtime.
"""

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
CONF_DEFECTO = HOME / ".optimizar-disco.conf"

# Firmas de imágenes de máquina virtual o de disco. Si una carpeta candidata contiene alguno de
# estos archivos, NO es basura: es una VM o un disco virtual que alguna app está usando.
# Verificado el 25/08/2026: 18 GB en un `vm_bundles` parecían caché y eran la VM activa de una app.
FIRMAS_VM = {"vmlinuz", "initrd", "rootfs.img", "sessiondata.img", "Docker.raw", "efivars.fd"}
EXT_VM = {".raw", ".qcow2", ".vmdk", ".vdi", ".img"}


# --------------------------------------------------------------------------- utilidades
def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def tam(ruta: Path) -> int:
    """Tamaño en bytes, vía du -sk (mucho más rápido que caminar el árbol en Python)."""
    if not ruta.exists():
        return 0
    out = sh(f'du -sk {json.dumps(str(ruta))} 2>/dev/null')
    try:
        return int(out.split()[0]) * 1024
    except Exception:
        return 0


def gb(b): return b / (1024 ** 3)


def humano(b):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or u == "TB":
            return f"{b:.0f} {u}" if u in ("B", "KB") else f"{b:.1f} {u}"
        b /= 1024


def fecha_mtime(ruta: Path) -> str:
    try:
        return datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def corto(ruta) -> str:
    s = str(ruta)
    return "~" + s[len(str(HOME)):] if s.startswith(str(HOME)) else s


def disco():
    out = sh("df -k /System/Volumes/Data").splitlines()
    if len(out) < 2:
        return {}
    c = out[1].split()
    return {
        "total_gb": round(int(c[1]) / 1024 / 1024, 1),
        "usado_gb": round(int(c[2]) / 1024 / 1024, 1),
        "libre_gb": round(int(c[3]) / 1024 / 1024, 1),
        "uso_pct": c[4],
    }


def procesos_vivos():
    """Rutas que aparecen en la línea de comandos de un proceso node/npm/python vivo."""
    rutas = set()
    for linea in sh("ps -Ao command= 2>/dev/null").splitlines():
        for tok in linea.split():
            if tok.startswith(str(HOME)):
                rutas.add(tok)
    return rutas


def es_vm(ruta: Path) -> bool:
    """¿Esta carpeta contiene una imagen de VM o de disco virtual?"""
    if not ruta.is_dir():
        return ruta.suffix in EXT_VM
    try:
        for hijo in list(ruta.iterdir())[:60]:
            if hijo.name in FIRMAS_VM or hijo.suffix in EXT_VM:
                return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------- config
def cargar_config(ruta: Path):
    cfg = {"dias": 180, "raices": [], "protegidos": []}
    if not ruta.exists():
        return cfg, None
    for linea in ruta.read_text().splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or ":" not in linea:
            continue
        clave, valor = (x.strip() for x in linea.split(":", 1))
        valor = os.path.expanduser(valor)
        if clave == "dias":
            try:
                cfg["dias"] = int(valor)
            except ValueError:
                pass
        elif clave == "raiz":
            cfg["raices"].append(valor)
        elif clave == "protegido":
            cfg["protegidos"].append(valor)
    return cfg, ruta


class Guardia:
    """Decide si una ruta está protegida. La lista gana sobre cualquier criterio automático."""

    def __init__(self, patrones):
        self.patrones = [os.path.expanduser(p) for p in patrones]

    def protegida(self, ruta) -> str:
        s = str(ruta)
        for p in self.patrones:
            if fnmatch.fnmatch(s, p) or fnmatch.fnmatch(s, p.rstrip("/") + "/*") or s.startswith(p.rstrip("/") + "/"):
                return p
        return ""


# --------------------------------------------------------------------------- candidatos
class Candidato:
    def __init__(self, ruta, categoria, razon, bytes_, fecha="", accion="borrar", destino=""):
        self.ruta, self.categoria, self.razon = str(ruta), categoria, razon
        self.bytes, self.fecha, self.accion, self.destino = bytes_, fecha, accion, destino

    def dict(self):
        return {
            "ruta": self.ruta, "categoria": self.categoria, "razon": self.razon,
            "bytes": self.bytes, "tamano": humano(self.bytes), "fecha": self.fecha,
            "accion": self.accion, "destino": self.destino,
        }


def buscar(cfg, guardia, dias, raices):
    cands, excluidos, avisos = [], [], []
    corte = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    vivos = procesos_vivos()

    def agregar(ruta, categoria, razon, fecha="", accion="borrar", destino="", minimo=1024 * 1024):
        ruta = Path(ruta)
        if not ruta.exists():
            return
        p = guardia.protegida(ruta)
        if p:
            excluidos.append({"ruta": str(ruta), "motivo": f"protegido por la config ({p})"})
            return
        if es_vm(ruta):
            excluidos.append({"ruta": str(ruta), "motivo": "contiene una imagen de VM o disco virtual, está en uso"})
            return
        if any(str(ruta) in v or v.startswith(str(ruta) + "/") for v in vivos):
            excluidos.append({"ruta": str(ruta), "motivo": "hay un proceso vivo usándola"})
            return
        b = tam(ruta)
        if b < minimo:
            return
        cands.append(Candidato(ruta, categoria, razon, b, fecha or fecha_mtime(ruta), accion, destino))

    # --- cachés de gestores de paquetes: se regeneran al instalar algo
    for ruta in [
        HOME / ".npm/_cacache", HOME / ".npm/_npx",
        HOME / "Library/Caches/pip", HOME / "Library/Caches/Homebrew",
        HOME / ".cache/yarn", HOME / "Library/Caches/Yarn",
        HOME / ".cargo/registry/cache", HOME / "Library/Caches/go-build",
        HOME / ".cache/pypoetry/cache", HOME / "Library/Caches/CocoaPods",
    ]:
        agregar(ruta, "cache-dev", "caché de gestor de paquetes, se regenera al instalar")

    # --- modelos de IA: el mayor hallazgo típico, y el que más cuidado necesita
    hub = HOME / ".cache/huggingface/hub"
    if hub.is_dir():
        for d in sorted(hub.glob("models--*")):
            f = fecha_mtime(d)
            if f < corte:
                agregar(d, "modelos-ia", f"modelo de HuggingFace sin modificar desde {f}", fecha=f)
            else:
                excluidos.append({"ruta": str(d), "motivo": f"modelo con actividad reciente ({f})"})
    ollama = HOME / ".ollama/models"
    if ollama.is_dir():
        manifiestos = sorted(ollama.glob("manifests/**/*"))
        detalle = [f"{m.parent.name}:{m.name} ({fecha_mtime(m)})" for m in manifiestos if m.is_file()]
        if sh("pgrep -x ollama").strip():
            excluidos.append({"ruta": str(ollama), "motivo": "ollama está corriendo ahora"})
        elif detalle:
            agregar(ollama, "modelos-ia",
                    "modelos de Ollama: " + ", ".join(detalle) +
                    ". Ollama solo guarda fecha de descarga, no de uso: confírmalo tú")

    # --- cachés de apps: hay que cerrarlas antes o los reescriben al vuelo
    if sh("pgrep -f 'Visual Studio Code'").strip():
        avisos.append("VS Code está abierto: sus cachés no se pueden vaciar ahora. Ciérralo y repite.")
    else:
        for sub, razon in [
            ("CachedExtensionVSIXs", "instaladores de extensiones que ya están instaladas"),
            ("WebStorage", "estado de webviews, se reconstruye"),
            ("CachedData", "caché de compilación, se reconstruye"),
            ("Cache", "caché, se reconstruye"),
        ]:
            agregar(HOME / "Library/Application Support/Code" / sub, "cache-apps", razon)
    for ruta, razon in [
        (HOME / "Library/Caches/Google", "caché de Chrome, se reconstruye"),
        (HOME / "Library/Caches/ms-playwright-mcp", "navegador headless temporal, se re-descarga"),
        (HOME / ".cache/puppeteer", "navegador headless, se re-descarga"),
    ]:
        agregar(ruta, "cache-apps", razon)

    # jobs de agentes de más de 2 días: los recientes pueden pertenecer a una sesión viva
    jobs = HOME / ".claude/jobs"
    if jobs.is_dir():
        limite = datetime.now() - timedelta(days=2)
        for d in jobs.iterdir():
            if d.is_dir() and datetime.fromtimestamp(d.stat().st_mtime) < limite:
                agregar(d, "cache-apps", "residuo de un trabajo en background ya terminado")

    # --- node_modules juzgados por la actividad real del repo que los contiene
    for raiz in raices:
        raiz = Path(os.path.expanduser(raiz))
        if not raiz.is_dir():
            continue
        salida = sh(f'find {json.dumps(str(raiz))} -type d -name node_modules -prune 2>/dev/null')
        for linea in salida.splitlines():
            nm = Path(linea)
            if not nm.is_dir():
                continue
            repo = nm.parent
            while repo != repo.parent and not (repo / ".git").exists():
                repo = repo.parent
            if not (repo / ".git").exists():
                excluidos.append({"ruta": str(nm), "motivo": "no está en un repo git: sin señal de actividad"})
                continue
            ult = sh(f'git -C {json.dumps(str(repo))} log -1 --format=%cs 2>/dev/null').strip()
            if not ult:
                continue
            if ult < corte:
                agregar(nm, "node-modules",
                        f"último commit del repo: {ult}. Se reinstala con 'npm install'", fecha=ult)
            else:
                excluidos.append({"ruta": str(nm), "motivo": f"repo activo, último commit {ult}"})

    # --- descargas: instaladores se borran; lo que el usuario creó se MUEVE, nunca se borra
    dl = HOME / "Downloads"
    if dl.is_dir():
        for f in sorted(dl.iterdir()):
            if f.is_file() and f.suffix.lower() in {".dmg", ".pkg", ".exe", ".msi"}:
                agregar(f, "descargas", "instalador de una app que ya está instalada, se re-descarga")
        for f in sorted(dl.iterdir()):
            if f.is_file() and f.suffix.lower() in {".mp4", ".mkv", ".avi", ".mov"} and tam(f) > 500 * 1024 ** 2:
                agregar(f, "descargas", "video grande: se mueve, NO se borra",
                        accion="mover", destino=str(HOME / "Movies"), minimo=0)

    # --- docker: se reporta, el prune lo decide el usuario
    if shutil.which("docker") and sh("docker info 2>/dev/null").strip():
        df_docker = sh("docker system df 2>/dev/null")
        if df_docker:
            avisos.append("Docker disponible. `docker system prune -f` libera lo reclamable; el archivo "
                          "Docker.raw NO se encoge solo (usa 'Reclaim space' en Docker Desktop).\n"
                          + "\n".join("      " + l for l in df_docker.strip().splitlines()))
    return cands, excluidos, avisos


def top_consumidores(n=12):
    out = sh(f'du -sk {HOME}/* {HOME}/.[a-z]* 2>/dev/null | sort -rn | head -{n}')
    filas = []
    for linea in out.splitlines():
        try:
            kb, ruta = linea.split("\t", 1)
            filas.append((corto(ruta), humano(int(kb) * 1024)))
        except ValueError:
            continue
    return filas


# --------------------------------------------------------------------------- informe
def informe(d, tops, cands, excluidos, avisos, dias, conf_origen):
    L = []
    L.append("=" * 72)
    L.append(f"DIAGNÓSTICO DE DISCO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append("=" * 72)
    if d:
        L.append(f"  {d['total_gb']} GB totales · {d['usado_gb']} GB usados · "
                 f"{d['libre_gb']} GB libres · {d['uso_pct']} de uso")
    L.append(f"  Corte de inactividad: {dias} días")
    L.append(f"  Config: {conf_origen or 'ninguna (defaults)'}")

    L.append("\nQUÉ OCUPA EL DISCO")
    for ruta, t in tops:
        L.append(f"  {t:>9}  {ruta}")

    total = sum(c.bytes for c in cands if c.accion == "borrar")
    L.append(f"\nOPORTUNIDADES: {humano(total)} recuperables en {len(cands)} rutas")
    categorias = {}
    for c in cands:
        categorias.setdefault(c.categoria, []).append(c)
    titulos = {
        "cache-dev": "Cachés de gestores de paquetes (se regeneran solos)",
        "modelos-ia": "Modelos de IA sin uso reciente",
        "cache-apps": "Cachés de aplicaciones",
        "node-modules": "node_modules de repos inactivos",
        "descargas": "Descargas",
    }
    for cat in ("modelos-ia", "cache-dev", "node-modules", "cache-apps", "descargas"):
        grupo = categorias.get(cat)
        if not grupo:
            continue
        sub = sum(c.bytes for c in grupo if c.accion == "borrar")
        L.append(f"\n  {titulos.get(cat, cat)} — {humano(sub)}")
        for c in sorted(grupo, key=lambda x: -x.bytes):
            marca = "MOVER " if c.accion == "mover" else ""
            L.append(f"    {humano(c.bytes):>9}  {c.fecha}  {marca}{corto(c.ruta)}")
            L.append(f"                           {c.razon}")

    if excluidos:
        L.append(f"\nEXCLUIDO A PROPÓSITO ({len(excluidos)} rutas)")
        L.append("  Esto es lo que un borrado a ciegas habría roto:")
        for e in excluidos[:25]:
            L.append(f"    {corto(e['ruta'])}")
            L.append(f"        {e['motivo']}")
        if len(excluidos) > 25:
            L.append(f"    ... y {len(excluidos) - 25} más")

    if avisos:
        L.append("\nAVISOS")
        for a in avisos:
            L.append(f"  - {a}")

    L.append("\nNADA SE BORRÓ. Este programa solo mide.")
    L.append("Para obtener el script de limpieza:  --generar limpiar-disco.sh")
    return "\n".join(L)


# --------------------------------------------------------------------------- generador
def generar_script(d, cands, excluidos, dias, destino: Path):
    """Emite un .sh autocontenido, legible y auditable, con las rutas literales medidas."""
    hoy = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = sum(c.bytes for c in cands if c.accion == "borrar")
    categorias = {}
    for c in cands:
        categorias.setdefault(c.categoria, []).append(c)

    out = []
    A = out.append
    A("#!/usr/bin/env bash")
    A(f"# Script de limpieza de disco generado el {hoy} por diagnosticar-disco.py")
    A("#")
    A("# LÉELO ANTES DE CORRERLO. Cada bloque dice qué borra, cuánto pesa y por qué se considera")
    A("# prescindible. Puedes editarlo, comentar líneas o borrar bloques completos: es texto plano")
    A("# y no depende de ningún otro programa.")
    A("#")
    if d:
        A(f"# Estado al generarlo: {d['usado_gb']} GB usados de {d['total_gb']} "
          f"({d['uso_pct']}), {d['libre_gb']} GB libres.")
    A(f"# Recuperable estimado: {humano(total)} en {len([c for c in cands if c.accion=='borrar'])} rutas.")
    A(f"# Criterio de inactividad: {dias} días sin modificación (o sin commits, para node_modules).")
    A("#")
    A("# Cada bloque pide confirmación escrita. No hay modo automático, a propósito.")
    A("#")
    A("# VERIFICADO Y EXCLUIDO al generar este script (NO aparece abajo):")
    for e in excluidos[:20]:
        A(f"#   {corto(e['ruta'])}")
        A(f"#       {e['motivo']}")
    if len(excluidos) > 20:
        A(f"#   ... y {len(excluidos) - 20} rutas más, por el mismo tipo de razón.")
    A("")
    A("set -uo pipefail")
    A("")
    A('libre() { df -k /System/Volumes/Data | awk \'NR==2{printf "%.1f", $4/1024/1024}\'; }')
    A('LIBRE_INICIAL="$(libre)"')
    A('echo "Libre al empezar: ${LIBRE_INICIAL} GB"')
    A("")
    A("confirmar() {")
    A('  printf \'\\n>>> %s\\n    Escribe "si" para ejecutar: \' "$1"')
    A("  local r; read -r r")
    A('  [ "$r" = "si" ]')
    A("}")
    A("")
    A("# borra reportando el peso; se niega a tocar / o el home")
    A("quitar() {")
    A('  local ruta="$1"')
    A('  case "$ruta" in ""|/|"$HOME"|"$HOME"/) echo "    ABORTA: ruta peligrosa"; return 1 ;; esac')
    A('  if [ ! -e "$ruta" ]; then echo "    --  ya no existe: $ruta"; return 0; fi')
    A('  local antes; antes="$(du -sh "$ruta" 2>/dev/null | cut -f1)"')
    A('  rm -rf "$ruta" && printf \'    ok  %-8s %s\\n\' "$antes" "$ruta"')
    A("}")
    A("")
    A("mover() {")
    A('  local ruta="$1" destino="$2"')
    A('  [ -e "$ruta" ] || { echo "    --  ya no existe: $ruta"; return 0; }')
    A('  mkdir -p "$destino"')
    A('  mv -n "$ruta" "$destino"/ && echo "    movido a $destino: $(basename "$ruta")"')
    A("}")

    titulos = {
        "modelos-ia": "MODELOS DE IA SIN USO RECIENTE",
        "cache-dev": "CACHÉS DE GESTORES DE PAQUETES",
        "node-modules": "NODE_MODULES DE REPOS INACTIVOS",
        "cache-apps": "CACHÉS DE APLICACIONES",
        "descargas": "DESCARGAS",
    }
    for cat in ("modelos-ia", "cache-dev", "node-modules", "cache-apps", "descargas"):
        grupo = sorted(categorias.get(cat, []), key=lambda x: -x.bytes)
        if not grupo:
            continue
        borrables = [c for c in grupo if c.accion == "borrar"]
        movibles = [c for c in grupo if c.accion == "mover"]
        sub = sum(c.bytes for c in borrables)
        A("")
        A("# " + "=" * 70)
        A(f"# {titulos.get(cat, cat.upper())} — {humano(sub)}")
        A("# " + "=" * 70)
        for c in grupo:
            A(f"#   {humano(c.bytes):>9}  {c.fecha}  {corto(c.ruta)}")
            A(f"#              {c.razon}")
        if borrables:
            A(f'echo; echo "=== {titulos.get(cat, cat)} ({humano(sub)}) ==="')
            A(f'if confirmar "Eliminar {len(borrables)} ruta(s), {humano(sub)}"; then')
            for c in borrables:
                A(f'  quitar {json.dumps(c.ruta)}')
            A("fi")
        if movibles:
            A(f'echo; echo "=== Mover {len(movibles)} archivo(s) grande(s) ==="')
            A('echo "NOTA: mover dentro del mismo volumen NO libera espacio, solo ordena."')
            A(f'if confirmar "Mover {len(movibles)} archivo(s)"; then')
            for c in movibles:
                A(f'  mover {json.dumps(c.ruta)} {json.dumps(c.destino)}')
            A("fi")

    A("")
    A('echo')
    A('echo "==================== RESULTADO ===================="')
    A('echo "Libre al empezar: ${LIBRE_INICIAL} GB"')
    A('echo "Libre ahora:      $(libre) GB"')
    A('df -h /System/Volumes/Data | sed -n \'1p;2p\'')
    destino.write_text("\n".join(out) + "\n")
    destino.chmod(0o755)
    return destino


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Diagnostica el disco y genera el script de limpieza.")
    ap.add_argument("--generar", metavar="RUTA", help="escribe el script de limpieza en RUTA")
    ap.add_argument("--json", action="store_true", help="salida estructurada")
    ap.add_argument("--dias", type=int, help="corte de inactividad en días")
    ap.add_argument("--raiz", action="append", default=[], help="dónde buscar node_modules (repetible)")
    ap.add_argument("--config", default=str(CONF_DEFECTO))
    args = ap.parse_args()

    cfg, origen = cargar_config(Path(os.path.expanduser(args.config)))
    dias = args.dias or cfg["dias"]
    raices = args.raiz or cfg["raices"] or [str(HOME)]
    guardia = Guardia(cfg["protegidos"])

    d = disco()
    cands, excluidos, avisos = buscar(cfg, guardia, dias, raices)

    if args.json:
        print(json.dumps({
            "disco": d, "dias": dias, "raices": raices,
            "recuperable_gb": round(gb(sum(c.bytes for c in cands if c.accion == "borrar")), 2),
            "candidatos": [c.dict() for c in cands],
            "excluidos": excluidos, "avisos": avisos,
        }, ensure_ascii=False, indent=2))
        return

    print(informe(d, top_consumidores(), cands, excluidos, avisos, dias, origen))
    if args.generar:
        ruta = generar_script(d, cands, excluidos, dias, Path(os.path.expanduser(args.generar)))
        print(f"\nScript de limpieza escrito en: {ruta}")
        print("Revísalo y córrelo cuando quieras:")
        print(f"  bash {ruta}")


if __name__ == "__main__":
    sys.exit(main())
