<script setup>
import { computed } from 'vue'
import { LETRAS, alternarTema, cambiarLetra, preferencias, temaActual } from '../preferencias'

// «todo» en el login; en la app, la barra muestra solo el tema y el menú de la cuenta, solo la letra
defineProps({ mostrar: { type: String, default: 'todo' } })

const oscuro = computed(() => temaActual.value === 'oscuro')
const porcentaje = computed(() => `${Math.round(preferencias.letra * 100)} %`)
</script>

<template>
  <div class="preferencias">
    <div v-if="mostrar !== 'tema'" class="letra" role="group" aria-label="Tamaño de letra">
      <button
        type="button"
        class="boton-icono"
        :disabled="preferencias.letra <= LETRAS[0]"
        title="Letra más pequeña"
        aria-label="Letra más pequeña"
        @click="cambiarLetra(-1)"
      >
        <span aria-hidden="true">A<sup>−</sup></span>
      </button>
      <output class="letra-valor" aria-live="polite" :title="`Tamaño de letra: ${porcentaje}`">{{ porcentaje }}</output>
      <button
        type="button"
        class="boton-icono"
        :disabled="preferencias.letra >= LETRAS[LETRAS.length - 1]"
        title="Letra más grande"
        aria-label="Letra más grande"
        @click="cambiarLetra(1)"
      >
        <span aria-hidden="true">A<sup>+</sup></span>
      </button>
    </div>
    <button
      v-if="mostrar !== 'letra'"
      type="button"
      class="boton-icono tema"
      :class="{ solo: mostrar === 'tema' }"
      :title="oscuro ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'"
      :aria-label="oscuro ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'"
      @click="alternarTema"
    >
      <svg v-if="oscuro" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <circle cx="12" cy="12" r="4.5" fill="currentColor" />
        <g stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" />
        </g>
      </svg>
      <svg v-else viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path fill="currentColor" d="M20.5 14.6A8.5 8.5 0 0 1 9.4 3.5a8.5 8.5 0 1 0 11.1 11.1Z" />
      </svg>
      <span v-if="mostrar === 'todo'" class="tema-texto">{{ oscuro ? 'Claro' : 'Oscuro' }}</span>
    </button>
  </div>
</template>
