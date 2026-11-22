<script setup>
import { ref } from 'vue'
import { api } from '../api'

const dialogo = ref(null)
const actual = ref('')
const nueva = ref('')
const repetida = ref('')
const error = ref('')
const listo = ref(false)
const enviando = ref(false)

function abrir() {
  actual.value = nueva.value = repetida.value = error.value = ''
  listo.value = false
  dialogo.value.showModal()
}

async function guardar() {
  error.value = ''
  if (nueva.value !== repetida.value) {
    error.value = 'Las contraseñas nuevas no coinciden'
    return
  }
  enviando.value = true
  try {
    await api('/auth/clave', { metodo: 'PUT', datos: { actual: actual.value, nueva: nueva.value } })
    listo.value = true
  } catch (e) {
    error.value = e.message
  } finally {
    enviando.value = false
  }
}

defineExpose({ abrir })
</script>

<template>
  <dialog ref="dialogo" class="dialogo" aria-labelledby="titulo-clave">
    <h2 id="titulo-clave">Cambiar contraseña</h2>
    <template v-if="listo">
      <p class="aviso exito">La contraseña se cambió.</p>
      <div class="acciones">
        <button type="button" class="boton" @click="dialogo.close()">Cerrar</button>
      </div>
    </template>
    <form v-else class="formulario" @submit.prevent="guardar">
      <label>Contraseña actual
        <input v-model="actual" type="password" autocomplete="current-password" required>
      </label>
      <label>Contraseña nueva
        <input v-model="nueva" type="password" autocomplete="new-password" minlength="8" required>
      </label>
      <label>Repite la contraseña nueva
        <input v-model="repetida" type="password" autocomplete="new-password" minlength="8" required>
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div class="acciones">
        <button type="button" class="boton secundario" @click="dialogo.close()">Cancelar</button>
        <button class="boton" :disabled="enviando">{{ enviando ? 'Guardando…' : 'Guardar' }}</button>
      </div>
    </form>
  </dialog>
</template>
