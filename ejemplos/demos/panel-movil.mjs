/**
 * Versión móvil del guion: recorrido más corto y sin las columnas que el layout móvil esconde.
 * Un guion de escritorio suele fallar en móvil porque sus selectores dejan de tener caja visible.
 */
export const config = { nombre: 'panel', url: 'http://127.0.0.1:21000/', perfil: 'movil', escala: 2 };

export default async function guion(page, u) {
  await u.pausa(600);
  await u.rotulo('Tu operación, en el teléfono', { ms: 2000 });
  await u.pausa(800);
  await u.escribir('#buscar', 'aceite');
  await u.pausa(1500);
  await u.escribir('#buscar', '');
  await u.pausa(500);
  await u.click('.chip:nth-of-type(2)');
  await u.rotulo('Solo lo pendiente', { ms: 1800 });
  await u.pausa(1400);
  await u.click('nav a[data-v="reportes"]');
  await u.rotulo('Cierre mensual listo', { ms: 2000 });
  await u.pausa(1800);
}
