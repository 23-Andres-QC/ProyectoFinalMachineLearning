export class ErrorApi extends Error {
  constructor(mensaje, estado) {
    super(mensaje)
    this.estado = estado
  }
}

// Todas las llamadas al backend pasan por aquí: la sesión va en una cookie httpOnly (el navegador la manda solo) y los errores
// llegan como {"error": "..."}. Un 401 fuera de /auth avisa a la app para volver al login.
export async function api(ruta, { metodo = 'GET', datos } = {}) {
  const opciones = { method: metodo, headers: {}, credentials: 'same-origin' }
  if (datos instanceof FormData) {
    opciones.body = datos
  } else if (datos !== undefined) {
    opciones.headers['Content-Type'] = 'application/json'
    opciones.body = JSON.stringify(datos)
  }
  let respuesta
  try {
    respuesta = await fetch('/api' + ruta, opciones)
  } catch {
    throw new ErrorApi('No se pudo conectar con el servidor', 0)
  }
  const cuerpo = await respuesta.json().catch(() => null)
  if (!respuesta.ok) {
    if (respuesta.status === 401 && !ruta.startsWith('/auth/')) {
      window.dispatchEvent(new Event('hidrosar:sesion-expirada'))
    }
    throw new ErrorApi(cuerpo?.error || `Error ${respuesta.status}`, respuesta.status)
  }
  return cuerpo
}
