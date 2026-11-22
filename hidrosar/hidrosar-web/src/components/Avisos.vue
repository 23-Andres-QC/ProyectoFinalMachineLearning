<script setup>
import { avisos, cerrarAviso } from '../avisos'
</script>

<template>
  <div class="avisos" role="status" aria-live="polite">
    <TransitionGroup name="aviso">
      <div v-for="a in avisos" :key="a.id" class="aviso-flotante" :class="a.tipo">
        <svg v-if="a.tipo === 'exito'" viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
          <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.15" />
          <path d="M6 10.5l2.5 2.5L14 7.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <svg v-else viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
          <circle cx="10" cy="10" r="9" fill="currentColor" opacity="0.15" />
          <path d="M10 5.5v5.5M10 14.2v.3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span>{{ a.texto }}</span>
        <button type="button" class="cerrar-aviso" aria-label="Cerrar aviso" @click="cerrarAviso(a.id)">×</button>
      </div>
    </TransitionGroup>
  </div>
</template>
