/**
 * Guion del demo de ejemplo. Graba la app de `ejemplos/app-demo/`.
 *
 * Sirve la app y grábalo con:
 *   cd ejemplos/app-demo && python3 -m http.server 21000 &
 *   node ../../skills/grabar-demo/scripts/grabar.mjs ../demos/panel.mjs --salida /tmp/grab
 *
 * El recorrido vive acá, no en las manos de quien graba: si la app cambia, se vuelve a correr
 * y el video sale igual.
 */
export const config = {
  nombre: 'panel',
  url: 'http://127.0.0.1:21000/',
  viewport: { width: 1440, height: 900 },
  escala: 2,
  tema: 'light',
};

export default async function guion(page, u) {
  await u.pausa(700);
  await u.rotulo('Panel de operación en tiempo real', { ms: 2200 });
  await u.pausa(900);

  // los KPI primero: es lo que mira cualquiera al abrir un panel
  await u.mover('.kpi:nth-child(2)');
  await u.pausa(700);
  await u.mover('.kpi:nth-child(4)');
  await u.pausa(900);

  await u.rotulo('Buscar sin filtros ni menús', { ms: 2000 });
  await u.escribir('#buscar', 'aceite');
  await u.pausa(1400);
  await u.escribir('#buscar', '');
  await u.pausa(600);

  await u.rotulo('Un clic para ver solo lo pendiente', { ms: 2000 });
  await u.click('.chip:nth-of-type(2)');
  await u.pausa(1500);
  await u.click('.chip:nth-of-type(1)');
  await u.pausa(700);

  await u.rotulo('Todo el flujo en un solo lugar', { ms: 2200 });
  await u.click('nav a[data-v="despachos"]');
  await u.pausa(1600);
  await u.click('nav a[data-v="reportes"]');
  await u.pausa(1800);
  await u.click('nav a[data-v="pesajes"]');
  await u.pausa(1200);
}
