<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Preferencias from '../components/Preferencias.vue'
import { temaActual } from '../preferencias'
import { iniciarSesion } from '../sesion'

const route = useRoute()
const router = useRouter()
const email = ref('')
const clave = ref('')
const error = ref('')
const enviando = ref(false)
const verClave = ref(false)
const mayusculas = ref(false)

// Aviso de Bloq Mayús mientras se escribe la contraseña
function revisarMayusculas(e) {
  mayusculas.value = Boolean(e.getModifierState?.('CapsLock'))
}

// Fondo: de día, la Tierra; de noche, lluvia sobre los árboles. Los dos a media velocidad y en bucle.
// Con movimiento reducido queda una foto fija del video que toca.
const movimientoReducido = window.matchMedia('(prefers-reduced-motion: reduce)')
const quieto = ref(movimientoReducido.matches)
const alCambiarMovimiento = (e) => (quieto.value = e.matches)
movimientoReducido.addEventListener('change', alCambiarMovimiento)
onBeforeUnmount(() => movimientoReducido.removeEventListener('change', alCambiarMovimiento))
const fondo = computed(() => (temaActual.value === 'oscuro' ? 'lluvia' : 'tierra'))
const video = ref(null)

// Los 2 primeros segundos de cada video son el fundido que cierra el bucle (el final se mezcla con el inicio):
// la primera vez arranca después de ese fundido
const INICIO = { tierra: 2, lluvia: 2 }

// El video va sin sonido; si el navegador igual bloquea la reproducción automática, queda la foto de portada
watch(video, (v) => {
  if (!v) return
  v.muted = true
  const saltar = () => {
    if (v.currentTime < INICIO[fondo.value]) v.currentTime = INICIO[fondo.value]
  }
  if (v.readyState >= 1) saltar()
  else v.addEventListener('loadedmetadata', saltar, { once: true })
  v.play().catch(() => {})
})

async function entrar() {
  error.value = ''
  // se vuelve a ocultar antes de enviar, así el gestor de contraseñas del navegador la reconoce
  verClave.value = false
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
    <div class="escena" aria-hidden="true">
      <video
        v-if="!quieto"
        :key="fondo"
        ref="video"
        class="escena-video"
        :src="`/fondo/${fondo}.mp4`"
        :poster="`/fondo/${fondo}.jpg`"
        autoplay
        muted
        loop
        playsinline
        disablepictureinpicture
        preload="auto"
      />
      <div v-else class="escena-foto" :class="fondo" />
      <div class="escena-velo" />
    </div>

    <div class="login-arriba">
      <Preferencias />
    </div>

    <section class="login-portada" aria-labelledby="titulo-login">
      <h1 id="titulo-login" class="login-titulo">Hidro<span>SAR</span></h1>
      <p class="login-lema">Encuentra el agua de lluvia que queda empozada en la ciudad con el radar del satélite NISAR.</p>
    </section>

    <form class="login-tarjeta" aria-labelledby="titulo-ingreso" @submit.prevent="entrar">
      <div class="login-marca">
        <img src="/favicon.svg" alt="" width="48" height="48">
        <div>
          <p class="login-sobre">Acceso a HidroSAR</p>
          <h2 id="titulo-ingreso">Inicia sesión</h2>
        </div>
      </div>
      <p class="login-ayuda">Entra con el correo y la contraseña que te dio el administrador.</p>

      <div class="campo">
        <label for="login-correo">Correo</label>
        <div class="campo-caja">
          <svg class="campo-icono" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="5" width="18" height="14" rx="2.5" />
            <path d="m4 7 8 6 8-6" />
          </svg>
          <input
            id="login-correo"
            v-model="email"
            type="email"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            placeholder="nombre@correo.com"
            required
            autofocus
          >
        </div>
      </div>

      <div class="campo">
        <label for="login-clave">Contraseña</label>
        <div class="campo-caja">
          <svg class="campo-icono" viewBox="0 0 24 24" aria-hidden="true">
            <rect x="4.5" y="10.5" width="15" height="10" rx="2.5" />
            <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
          </svg>
          <input
            id="login-clave"
            v-model="clave"
            :type="verClave ? 'text' : 'password'"
            autocomplete="current-password"
            placeholder="Tu contraseña"
            required
            :aria-describedby="mayusculas ? 'aviso-mayusculas' : undefined"
            @keydown="revisarMayusculas"
            @keyup="revisarMayusculas"
            @blur="mayusculas = false"
          >
          <button
            type="button"
            class="ver-clave"
            aria-controls="login-clave"
            :aria-pressed="verClave"
            :aria-label="verClave ? 'Ocultar contraseña' : 'Mostrar contraseña'"
            :title="verClave ? 'Ocultar contraseña' : 'Mostrar contraseña'"
            @click="verClave = !verClave"
          >
            <svg v-if="!verClave" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true">
              <path d="M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.7 3.5M6.6 6.6C3.9 8.3 2.5 12 2.5 12S6 18.5 12 18.5a9 9 0 0 0 5.4-1.9" />
              <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />
            </svg>
          </button>
        </div>
        <p v-if="mayusculas" id="aviso-mayusculas" class="aviso-mayusculas">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4 4 12h4.5v4h7v-4H20Z" /><path d="M8.5 19.5h7" /></svg>
          Bloq Mayús está activado
        </p>
      </div>

      <p v-if="error" class="login-error" role="alert">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7.5v5.5M12 16.4v.2" /></svg>
        {{ error }}
      </p>

      <button class="boton-login" :disabled="enviando">
        <span v-if="enviando" class="girando" aria-hidden="true"></span>
        {{ enviando ? 'Ingresando…' : 'Ingresar' }}
        <svg v-if="!enviando" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6.5 18.5 12 13 17.5" /></svg>
      </button>

      <p class="login-pie">¿No tienes cuenta? Pídela al administrador de HidroSAR.</p>
    </form>
  </div>
</template>
