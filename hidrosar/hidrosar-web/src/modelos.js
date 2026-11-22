// Catálogo de modelos del servicio del modelo (llega dentro de /api/salud) y el modelo elegido en el mapa.
import { ref, shallowRef } from 'vue'
import { api } from './api'

const CLAVE = 'hidrosar:modelo'

export const catalogo = shallowRef([])
export const predeterminado = ref('')
let pedido = null

export function usarSalud(salud) {
  catalogo.value = salud?.modelo?.modelos || []
  predeterminado.value = salud?.modelo?.predeterminado || ''
}

export function cargarCatalogo() {
  if (!pedido) {
    pedido = api('/salud')
      .then(usarSalud)
      .catch(() => {
        pedido = null
      })
  }
  return pedido
}

export const infoModelo = (id) => catalogo.value.find((m) => m.id === (id || predeterminado.value)) || null
// un id que ya no está en el catálogo es de un modelo que se quitó (las evaluaciones viejas lo siguen guardando)
export const nombreModelo = (id) => {
  if (!id) return ''
  const nombre = infoModelo(id)?.nombre
  if (nombre) return nombre
  return catalogo.value.length ? `${id.split('/').pop()} (retirado)` : id
}

export function modeloGuardado() {
  try {
    return localStorage.getItem(CLAVE) || ''
  } catch {
    return ''
  }
}

export function guardarModelo(id) {
  try {
    localStorage.setItem(CLAVE, id)
  } catch {
    // sin almacenamiento (ventana privada): se elige de nuevo la próxima vez
  }
}
