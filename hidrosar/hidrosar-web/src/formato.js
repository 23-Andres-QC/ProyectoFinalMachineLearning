// "2026-10-24 06:12" o "2026-10-24" -> "24/10/2026 06:12" o "24/10/2026"
export function fechaCorta(texto) {
  if (!texto) return '—'
  const [dia, hora] = texto.split(' ')
  const [a, m, d] = dia.split('-')
  return `${d}/${m}/${a}${hora ? ' ' + hora : ''}`
}

export function fechaHora(iso, zona) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-PE', { timeZone: zona || undefined, dateStyle: 'short', timeStyle: 'short' })
}

export function area(m2) {
  if (m2 == null) return '—'
  if (m2 >= 10000) return `${(m2 / 10000).toLocaleString('es-PE', { maximumFractionDigits: 2 })} ha`
  return `${Math.round(m2).toLocaleString('es-PE')} m²`
}

export function mm(valor) {
  return valor == null ? '—' : `${valor.toLocaleString('es-PE', { maximumFractionDigits: 1 })} mm`
}

export const ESTADOS = {
  en_cola: 'En cola',
  procesando: 'Procesando',
  completado: 'Completado',
  error: 'Error',
}

export function hoyEn(zona) {
  return new Date().toLocaleDateString('en-CA', { timeZone: zona || undefined })
}
