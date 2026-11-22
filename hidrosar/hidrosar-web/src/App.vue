<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import CambiarClave from './components/CambiarClave.vue'
import { cerrarSesion, sesion } from './sesion'

const router = useRouter()
const dialogoClave = ref(null)

async function salir() {
  await cerrarSesion()
  router.push('/login')
}
</script>

<template>
  <header v-if="sesion.usuario" class="barra">
    <RouterLink to="/" class="marca">
      <img src="/favicon.svg" alt="" width="26" height="26">
      HidroSAR
    </RouterLink>
    <nav class="navegacion">
      <RouterLink to="/">Mapa</RouterLink>
      <RouterLink to="/lluvias">Lluvias</RouterLink>
      <RouterLink to="/evaluaciones">Evaluaciones</RouterLink>
      <RouterLink v-if="sesion.usuario.rol === 'administrador'" to="/usuarios">Usuarios</RouterLink>
    </nav>
    <div class="cuenta">
      <span class="quien">
        {{ sesion.usuario.nombre }}
        <span class="etiqueta">{{ sesion.usuario.rol }}</span>
      </span>
      <button type="button" class="boton-texto" @click="dialogoClave.abrir()">Contraseña</button>
      <button type="button" class="boton-texto" @click="salir">Salir</button>
    </div>
  </header>
  <main class="contenido">
    <RouterView />
  </main>
  <CambiarClave ref="dialogoClave" />
</template>
