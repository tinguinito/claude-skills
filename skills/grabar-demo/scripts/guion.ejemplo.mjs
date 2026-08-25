/**
 * Plantilla de guion. Copiar a <proyecto>/demos/<nombre>.mjs y adaptar.
 * Cada guion vive EN EL REPO del proyecto: así el recorrido se regraba idéntico
 * cuando la app cambia, que es la razón de grabar con código y no a mano.
 */
export const config = {
  nombre: 'mi-demo',
  url: 'http://localhost:5173',
  perfil: 'escritorio',   // 'escritorio' (1600x1000) o 'movil' (500x990)
  // viewport: { width: 1552, height: 992 },  // opcional, manda sobre el perfil
  escala: 2,              // deviceScaleFactor: 2 = texto nítido
  tema: 'light',
};

export default async function guion(page, u) {
  await u.rotulo('Panel de control');
  await u.pausa(1200);

  await u.click('text=Ingresar');
  await u.esperar('[data-testid="dashboard"]');
  await u.scroll(600);
  await u.pausa(1000);

  await u.escribir('input[name="buscar"]', 'informe mensual');
  await u.pausa(800);

  await u.rotulo('Todo el historial en un solo lugar', { ms: 3000 });
}
