<script setup>
// Pasos de una evaluación tal como los informa el servicio del modelo: hecho, en curso, pendiente o con error,
// con su detalle (MB descargados, cobertura, charcos) y los segundos que tomó cada uno.
defineProps({ pasos: { type: Array, required: true } })

const ESTADO = { hecho: 'Hecho', en_curso: 'En curso', pendiente: 'Pendiente', error: 'Falló' }
const tiempo = (s) => (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`)
</script>

<template>
  <ol class="pasos-proceso">
    <li v-for="p in pasos" :key="p.clave" :class="p.estado" :aria-current="p.estado === 'en_curso' ? 'step' : undefined">
      <span class="marca-paso" aria-hidden="true"></span>
      <span class="texto-paso">
        <span><span class="oculto">{{ ESTADO[p.estado] || p.estado }}: </span>{{ p.texto }}</span>
        <small v-if="p.detalle">{{ p.detalle }}</small>
      </span>
      <span v-if="p.segundos != null" class="tiempo-paso">{{ tiempo(p.segundos) }}</span>
    </li>
  </ol>
</template>
