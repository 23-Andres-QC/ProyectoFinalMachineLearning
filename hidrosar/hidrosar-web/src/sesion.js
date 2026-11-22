import { reactive } from 'vue'
import { api } from './api'

export const sesion = reactive({ usuario: null, cargada: false })

export async function cargarSesion() {
  try {
    sesion.usuario = (await api('/auth/yo')).usuario
  } catch {
    sesion.usuario = null
  }
  sesion.cargada = true
}

export async function iniciarSesion(email, clave) {
  sesion.usuario = (await api('/auth/login', { metodo: 'POST', datos: { email, clave } })).usuario
}

export async function cerrarSesion() {
  try {
    await api('/auth/logout', { metodo: 'POST' })
  } finally {
    sesion.usuario = null
  }
}
