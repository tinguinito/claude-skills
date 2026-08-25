#!/usr/bin/env node
/**
 * Grabador de demos con Playwright.
 *
 * Uso:  node grabar.mjs <guion.mjs> [--salida DIR] [--perfil escritorio|movil] [--headed]
 *
 * El guion es un módulo ES que exporta:
 *   export const config = { nombre, url, perfil?, viewport?, escala? }
 *   export default async function guion(page, u) { ... }
 *
 * Playwright graba SOLO el viewport: no hay marco de ventana ni barra de URL en el
 * archivo resultante, así que el "localhost:5173" nunca aparece. Esa es la razón
 * principal de grabar así y no con captura de pantalla del sistema.
 */
import { chromium } from 'playwright';
import { pathToFileURL } from 'node:url';
import { mkdirSync, readdirSync, renameSync } from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
if (!args[0]) { console.error('Falta el guion. Uso: node grabar.mjs <guion.mjs> [--salida DIR] [--perfil escritorio|movil] [--headed]'); process.exit(1); }

const guionPath = path.resolve(args[0]);
const opt = (n, def) => { const i = args.indexOf('--' + n); return i >= 0 ? args[i + 1] : def; };
const salida = path.resolve(opt('salida', path.join(process.cwd(), 'grabaciones')));
const headed = args.includes('--headed');

const PERFILES = {
  escritorio: { width: 1600, height: 1000 },
  movil: { width: 500, height: 990 },
};

const mod = await import(pathToFileURL(guionPath).href);
const config = mod.config ?? {};
const guion = mod.default;
if (typeof guion !== 'function') { console.error('El guion debe exportar por defecto una función async (page, u).'); process.exit(1); }

const perfilCLI = args.includes('--perfil');
const perfil = opt('perfil', config.perfil ?? 'escritorio');
// Un --perfil explícito en la línea de comandos manda sobre el viewport del guion:
// así el mismo guion se graba en escritorio y en móvil sin editarlo.
const viewport = (perfilCLI ? PERFILES[perfil] : config.viewport ?? PERFILES[perfil]) ?? PERFILES.escritorio;
const nombre = config.nombre ?? path.basename(guionPath, '.mjs');

mkdirSync(salida, { recursive: true });

const browser = await chromium.launch({ headless: !headed });
const context = await browser.newContext({
  viewport,
  deviceScaleFactor: config.escala ?? 2,
  isMobile: perfil === 'movil',
  hasTouch: perfil === 'movil',
  locale: config.locale ?? 'es-CL',
  timezoneId: config.timezone ?? 'America/Santiago',
  colorScheme: config.tema ?? 'light',
  recordVideo: { dir: salida, size: viewport },
});

const page = await context.newPage();

// Redirección de hosts (config.redirigir = { 'localhost:9099': '127.0.0.1:9098' }).
// Sirve cuando un servicio local del proyecto (por ejemplo un emulador de Firebase)
// está en otro puerto porque el habitual lo ocupa otra sesión de trabajo.
for (const [desde, hacia] of Object.entries(config.redirigir ?? {})) {
  await page.route(`**://${desde}/**`, async (ruta) => {
    const req = ruta.request();
    const destino = req.url().replace(desde, hacia);
    const r = await page.request.fetch(destino, {
      method: req.method(), headers: req.headers(), data: req.postData() ?? undefined,
    });
    await ruta.fulfill({ response: r });
  });
}

// Cursor visible: sin esto el video muestra cambios sin causa aparente.
await page.addInitScript(() => {
  const pintar = () => {
    if (document.getElementById('__cursor_demo')) return;
    const c = document.createElement('div');
    c.id = '__cursor_demo';
    c.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'width:22px', 'height:22px',
      'border-radius:50%', 'background:rgba(123,45,142,.28)',
      'border:2px solid rgba(123,45,142,.85)', 'box-shadow:0 2px 8px rgba(0,0,0,.25)',
      'pointer-events:none', 'z-index:2147483647',
      'transform:translate(-50%,-50%)', 'transition:width .12s,height .12s,background .12s',
    ].join(';');
    document.documentElement.appendChild(c);
    window.__moverCursor = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
    window.__pulsoCursor = () => {
      c.style.width = '34px'; c.style.height = '34px'; c.style.background = 'rgba(171,189,7,.45)';
      setTimeout(() => { c.style.width = '22px'; c.style.height = '22px'; c.style.background = 'rgba(123,45,142,.28)'; }, 180);
    };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', pintar);
  else pintar();
  window.addEventListener('load', pintar);
});

let pos = { x: viewport.width / 2, y: viewport.height / 2 };
const dormir = (ms) => new Promise((r) => setTimeout(r, ms));

/** Utilidades del guion. Todo es lento a propósito: un demo legible, no un test. */
const u = {
  page,
  viewport,
  perfil,
  /** Pausa explícita, en ms. Úsala para dar tiempo de lectura. */
  pausa: dormir,
  /** Mueve el cursor en curva suave hasta un punto o selector. */
  async mover(destino, pasos = 22) {
    const p = await puntoDe(destino);
    for (let i = 1; i <= pasos; i++) {
      const t = i / pasos;
      const e = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // easeInOut
      const x = pos.x + (p.x - pos.x) * e;
      const y = pos.y + (p.y - pos.y) * e;
      await page.mouse.move(x, y);
      await page.evaluate(([x, y]) => window.__moverCursor?.(x, y), [x, y]).catch(() => {});
      await dormir(14);
    }
    pos = p;
  },
  /** Mueve el cursor hasta el elemento y hace clic con pulso visible. */
  async click(selector, { espera = 700 } = {}) {
    await page.locator(selector).first().scrollIntoViewIfNeeded().catch(() => {});
    await u.mover(selector);
    await page.evaluate(() => window.__pulsoCursor?.()).catch(() => {});
    await page.locator(selector).first().click();
    await dormir(espera);
  },
  /** Escribe con ritmo humano. */
  async escribir(selector, texto, { delay = 85, espera = 500 } = {}) {
    await u.mover(selector);
    await page.locator(selector).first().click();
    await page.locator(selector).first().pressSequentially(texto, { delay });
    await dormir(espera);
  },
  /** Scroll suave de N píxeles (o hasta un selector). */
  async scroll(cantidad, { duracion = 900 } = {}) {
    if (typeof cantidad === 'string') {
      await page.locator(cantidad).first().scrollIntoViewIfNeeded();
      await dormir(duracion);
      return;
    }
    const pasos = Math.max(8, Math.round(duracion / 40));
    for (let i = 0; i < pasos; i++) {
      await page.mouse.wheel(0, cantidad / pasos);
      await dormir(duracion / pasos);
    }
  },
  /** Espera a que un selector esté visible antes de seguir. */
  async esperar(selector, { timeout = 15000 } = {}) {
    await page.locator(selector).first().waitFor({ state: 'visible', timeout });
  },
  /** Inyecta CSS en la página (persiste mientras no haya recarga completa). */
  async css(reglas) {
    await page.addStyleTag({ content: reglas });
  },
  /**
   * Oculta de forma permanente cualquier elemento que contenga un texto.
   * Para banners de estado de los datos de prueba (avisos de suscripción,
   * bandas de entorno) que no son parte del producto que se quiere mostrar.
   */
  async ocultarTexto(...textos) {
    await page.evaluate((textos) => {
      const ocultar = () => {
        for (const t of textos) {
          // El nodo más profundo que contiene el texto: subir a un ancestro
          // grande esconde media pantalla (pasó con la barra de búsqueda).
          const candidatos = [...document.querySelectorAll('div,section,header,aside,p,span')]
            .filter((el) => el.textContent?.includes(t))
            .filter((el) => ![...el.children].some((h) => h.textContent?.includes(t)));
          for (const el of candidatos) {
            // Sube un solo nivel si el padre es la banda que envuelve al texto
            // (mismo texto, pocos hijos): así se va también el botón de al lado.
            const padre = el.parentElement;
            const caja = padre && padre.children.length <= 3 && padre !== document.body ? padre : el;
            caja.style.display = 'none';
          }
        }
      };
      ocultar();
      window.__ocultarDemo && clearInterval(window.__ocultarDemo);
      window.__ocultarDemo = setInterval(ocultar, 400);
    }, textos);
    await new Promise((r) => setTimeout(r, 300));
  },
  /** Rótulo sobreimpreso para nombrar lo que se está mostrando. */
  async rotulo(texto, { ms = 2600, posicion = 'inferior' } = {}) {
    await page.evaluate(([texto, posicion]) => {
      const d = document.createElement('div');
      d.className = '__rotulo_demo';
      const abajo = posicion === 'inferior';
      d.style.cssText = [
        'position:fixed', 'left:50%', abajo ? 'bottom:42px' : 'top:42px', 'transform:translateX(-50%)',
        'background:rgba(20,10,25,.88)', 'color:#fff', 'padding:12px 22px', 'border-radius:10px',
        'font:600 17px/1.35 Montserrat,system-ui,sans-serif', 'letter-spacing:.2px',
        'max-width:78%', 'text-align:center', 'z-index:2147483646',
        'opacity:0', 'transition:opacity .35s', 'pointer-events:none',
        'box-shadow:0 8px 28px rgba(0,0,0,.3)',
      ].join(';');
      d.textContent = texto;
      document.documentElement.appendChild(d);
      requestAnimationFrame(() => { d.style.opacity = '1'; });
    }, [texto, posicion]);
    await dormir(ms);
    await page.evaluate(() => {
      document.querySelectorAll('.__rotulo_demo').forEach((d) => {
        d.style.opacity = '0';
        setTimeout(() => d.remove(), 400);
      });
    });
    await dormir(420);
  },
};

async function puntoDe(destino) {
  if (typeof destino === 'object' && destino && 'x' in destino) return destino;
  const caja = await page.locator(destino).first().boundingBox();
  if (!caja) throw new Error(`No se encontró el elemento para mover el cursor: ${destino}`);
  return { x: caja.x + caja.width / 2, y: caja.y + caja.height / 2 };
}

let error = null;
try {
  if (config.url) {
    await page.goto(config.url, { waitUntil: 'networkidle' });
    await dormir(1200);
  }
  await guion(page, u);
  await dormir(900); // cola: evita que el video corte en seco
} catch (e) {
  error = e;
  console.error('El guion falló:', e.message);
}

await context.close();
await browser.close();

// Renombrar el .webm que deja Playwright a un nombre estable.
const webm = readdirSync(salida).filter((f) => f.endsWith('.webm')).map((f) => path.join(salida, f))
  .sort((a, b) => a.localeCompare(b)).pop();
if (webm) {
  const destino = path.join(salida, `${nombre}-${perfil}.webm`);
  renameSync(webm, destino);
  console.log(destino);
}
process.exit(error ? 1 : 0);
