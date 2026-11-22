import { reactive } from 'vue'

// Avisos breves de la app ("Evaluación #12 eliminada"): aparecen abajo a la derecha y se van solos.
export const avisos = reactive([])
let siguiente = 1

export function avisar(texto, tipo = 'exito', duracion = 4500) {
  const id = siguiente++
  avisos.push({ id, texto, tipo })
  setTimeout(() => cerrarAviso(id), duracion)
}

export function cerrarAviso(id) {
  const i = avisos.findIndex((a) => a.id === id)
  if (i >= 0) avisos.splice(i, 1)
}
