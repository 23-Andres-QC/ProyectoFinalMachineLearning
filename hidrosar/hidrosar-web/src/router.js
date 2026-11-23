import { createRouter, createWebHistory } from 'vue-router'
import { cargarSesion, sesion } from './sesion'
import LoginView from './views/LoginView.vue'

const rutas = [
  { path: '/login', component: LoginView, meta: { publica: true, titulo: 'Ingresar' } },
  { path: '/', component: () => import('./views/MapaView.vue'), meta: { titulo: 'Mapa' } },
  { path: '/lluvias', component: () => import('./views/LluviasView.vue'), meta: { titulo: 'Lluvias' } },
  { path: '/evaluaciones', component: () => import('./views/EvaluacionesView.vue'), meta: { titulo: 'Evaluaciones' } },
  { path: '/validaciones', component: () => import('./views/ValidacionesView.vue'), meta: { titulo: 'Validaciones' } },
  { path: '/usuarios', component: () => import('./views/UsuariosView.vue'), meta: { admin: true, titulo: 'Usuarios' } },
  { path: '/:resto(.*)*', redirect: '/' },
]

export const router = createRouter({ history: createWebHistory(), routes: rutas })

router.beforeEach(async (destino) => {
  if (!sesion.cargada) await cargarSesion()
  if (destino.meta.publica) return sesion.usuario ? '/' : true
  if (!sesion.usuario) return { path: '/login', query: destino.fullPath === '/' ? {} : { volver: destino.fullPath } }
  if (destino.meta.admin && sesion.usuario.rol !== 'administrador') return '/'
  return true
})

router.afterEach((destino) => {
  document.title = `${destino.meta.titulo} · HidroSAR`
})

window.addEventListener('hidrosar:sesion-expirada', () => {
  sesion.usuario = null
  router.push('/login')
})
