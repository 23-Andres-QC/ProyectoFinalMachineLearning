<script setup>
import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import Avisos from './components/Avisos.vue'
import CambiarClave from './components/CambiarClave.vue'
import Icono from './components/Icono.vue'
import MenuUsuario from './components/MenuUsuario.vue'
import Preferencias from './components/Preferencias.vue'
import { cerrarSesion, sesion } from './sesion'

const router = useRouter()
const dialogoClave = ref(null)
const principal = ref(null)

async function salir() {
  await cerrarSesion()
  router.push('/login')
}

// Al cambiar de página, el foco pasa al contenido (así un lector de pantalla anuncia la página nueva)
let primera = true
router.afterEach(async () => {
  if (primera) {
    primera = false
    return
  }
  await nextTick()
  principal.value?.focus({ preventScroll: true })
})
</script>

<template>
  <a href="#contenido" class="saltar">Saltar al contenido</a>
  <header v-if="sesion.usuario" class="barra">
    <RouterLink to="/" class="marca" aria-label="HidroSAR, ir al mapa">
      <img src="/favicon.svg" alt="" width="30" height="30">
      <span>Hidro<b>SAR</b></span>
    </RouterLink>
    <nav class="navegacion" aria-label="Secciones">
      <RouterLink to="/"><Icono nombre="mapa" /><span>Mapa</span></RouterLink>
      <RouterLink to="/lluvias"><Icono nombre="lluvia" /><span>Lluvias</span></RouterLink>
      <RouterLink to="/evaluaciones"><Icono nombre="lista" /><span>Evaluaciones</span></RouterLink>
      <RouterLink to="/validaciones"><Icono nombre="modelo" /><span>Validaciones</span></RouterLink>
      <RouterLink v-if="sesion.usuario.rol === 'administrador'" to="/usuarios"><Icono nombre="usuarios" /><span>Usuarios</span></RouterLink>
    </nav>
    <div class="cuenta">
      <Preferencias mostrar="tema" />
      <MenuUsuario @clave="dialogoClave.abrir()" @salir="salir" />
    </div>
  </header>
  <main id="contenido" ref="principal" class="contenido" :class="{ completo: !sesion.usuario }" tabindex="-1">
    <RouterView />
  </main>
  <CambiarClave ref="dialogoClave" />
  <Avisos />
</template>
