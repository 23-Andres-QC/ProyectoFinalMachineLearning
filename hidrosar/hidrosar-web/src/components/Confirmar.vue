<script setup>
import { ref } from 'vue'

// Diálogo modal nativo que devuelve una promesa: true si se acepta, false si se cancela o se cierra con Esc.
const dialogo = ref(null)
const titulo = ref('')
const texto = ref('')
const aceptar = ref('Aceptar')
const peligro = ref(false)
let resolver = null
let resultado = false

function preguntar(opciones) {
  titulo.value = opciones.titulo
  texto.value = opciones.texto || ''
  aceptar.value = opciones.aceptar || 'Aceptar'
  peligro.value = !!opciones.peligro
  resultado = false
  dialogo.value.showModal()
  return new Promise((r) => (resolver = r))
}

function responder(valor) {
  resultado = valor
  dialogo.value.close()
}

function alCerrar() {
  resolver?.(resultado)
  resolver = null
}

defineExpose({ preguntar })
</script>

<template>
  <dialog ref="dialogo" class="dialogo" :aria-label="titulo" @close="alCerrar">
    <h2>{{ titulo }}</h2>
    <p v-if="texto">{{ texto }}</p>
    <slot />
    <div class="acciones">
      <button type="button" class="boton secundario" @click="responder(false)">Cancelar</button>
      <button type="button" class="boton" :class="{ peligro }" @click="responder(true)">{{ aceptar }}</button>
    </div>
  </dialog>
</template>
