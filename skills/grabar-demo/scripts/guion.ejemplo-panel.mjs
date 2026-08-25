export const config = {
  nombre: 'ejemplo-panel',
  url: 'https://ejemplo.test',   // reemplaza por la URL de tu app
  perfil: 'escritorio',
  viewport: { width: 1552, height: 970 },
};

export default async function guion(page, u) {
  await u.rotulo('Panel de control de operaciones');
  await u.scroll(500);
  await u.pausa(800);
  await u.click('a:has-text("Cotizaciones")');
  await u.esperar('h1');
  await u.rotulo('Cotizaciones en un solo lugar', { ms: 2200 });
  await u.escribir('input[placeholder*="Buscar"]', 'OT-2026');
  await u.pausa(900);
}
