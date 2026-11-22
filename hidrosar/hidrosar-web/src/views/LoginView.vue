<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { iniciarSesion } from '../sesion'

const route = useRoute()
const router = useRouter()
const email = ref('')
const clave = ref('')
const error = ref('')
const enviando = ref(false)

async function entrar() {
  error.value = ''
  enviando.value = true
  try {
    await iniciarSesion(email.value, clave.value)
    const volver = route.query.volver
    router.replace(typeof volver === 'string' && volver.startsWith('/') && !volver.startsWith('//') ? volver : '/')
  } catch (e) {
    error.value = e.message
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <div class="login">
    <form class="tarjeta login-tarjeta formulario" @submit.prevent="entrar">
      <div class="login-marca">
        <img src="/favicon.svg" alt="" width="44" height="44">
        <div>
          <h1>HidroSAR</h1>
          <p class="tenue">Agua de lluvia empozada con radar NISAR</p>
        </div>
      </div>
      <label>Correo
        <input v-model="email" type="email" autocomplete="username" required autofocus>
      </label>
      <label>Contraseña
        <input v-model="clave" type="password" autocomplete="current-password" required>
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="boton ancho" :disabled="enviando">{{ enviando ? 'Ingresando…' : 'Ingresar' }}</button>
    </form>
  </div>
</template>
