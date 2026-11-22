import { computed, reactive } from 'vue'

// Tamaño de letra y tema (claro u oscuro) elegidos por la persona; se recuerdan en este navegador.
const CLAVE = 'hidrosar:preferencias'
export const LETRAS = [0.875, 1, 1.125, 1.25, 1.375]

const sistemaOscuro = window.matchMedia('(prefers-color-scheme: dark)')
let guardadas = {}
try {
  guardadas = JSON.parse(localStorage.getItem(CLAVE) || '{}') || {}
} catch {
  guardadas = {}
}

export const preferencias = reactive({
  letra: LETRAS.includes(guardadas.letra) ? guardadas.letra : 1,
  tema: ['claro', 'oscuro'].includes(guardadas.tema) ? guardadas.tema : null,
  sistema: sistemaOscuro.matches ? 'oscuro' : 'claro',
})

sistemaOscuro.addEventListener('change', (e) => {
  preferencias.sistema = e.matches ? 'oscuro' : 'claro'
})

export const temaActual = computed(() => preferencias.tema ?? preferencias.sistema)

function aplicar() {
  const raiz = document.documentElement
  raiz.style.setProperty('--escala', String(preferencias.letra))
  if (preferencias.tema) raiz.dataset.tema = preferencias.tema
  else delete raiz.dataset.tema
  try {
    localStorage.setItem(CLAVE, JSON.stringify({ letra: preferencias.letra, tema: preferencias.tema }))
  } catch {
    // sin almacenamiento: la preferencia dura hasta cerrar la pestaña
  }
}

export function cambiarLetra(paso) {
  const i = LETRAS.indexOf(preferencias.letra) + paso
  if (i < 0 || i >= LETRAS.length) return
  preferencias.letra = LETRAS[i]
  aplicar()
}

export function alternarTema() {
  preferencias.tema = temaActual.value === 'oscuro' ? 'claro' : 'oscuro'
  aplicar()
}

aplicar()
