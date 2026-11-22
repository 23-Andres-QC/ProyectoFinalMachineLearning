<script setup>
// Íconos de trazo (24 × 24) dibujados para HidroSAR; heredan el color del texto.
defineProps({
  nombre: { type: String, required: true },
  tam: { type: [Number, String], default: 18 },
})

const ICONOS = {
  mapa: ['M9 4 3.5 6.2v13.6L9 17.6l6 2.4 5.5-2.2V4.2L15 6.4 9 4Z', 'M9 4v13.6', 'M15 6.4V20'],
  lluvia: ['M7 15.5h10.2a3.6 3.6 0 0 0 .5-7.15 5.6 5.6 0 0 0-10.9 1.2A3 3 0 0 0 7 15.5Z', 'm8.5 18.5-.8 2', 'm12.5 18.5-.8 2', 'm16.5 18.5-.8 2'],
  lista: [
    'M9 3.5h6a1 1 0 0 1 1 1V6a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z',
    'M16 5h1.5A1.5 1.5 0 0 1 19 6.5v13a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19.5v-13A1.5 1.5 0 0 1 6.5 5H8',
    'M8.5 12h7',
    'M8.5 16h4.5',
  ],
  usuarios: [
    'M15.5 20v-1.5a3.5 3.5 0 0 0-3.5-3.5H7a3.5 3.5 0 0 0-3.5 3.5V20',
    'M13 8a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z',
    'M20.5 20v-1.5a3.5 3.5 0 0 0-2.6-3.4',
    'M15.5 4.6a3.5 3.5 0 0 1 0 6.8',
  ],
  llave: ['M11.5 15a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z', 'm10.4 12.1 8.6-8.6', 'm16.5 6 2.5 2.5', 'm14 8.5 2 2'],
  salir: ['M14 4h3.5A2.5 2.5 0 0 1 20 6.5v11a2.5 2.5 0 0 1-2.5 2.5H14', 'M9.5 16.5 5 12l4.5-4.5', 'M5 12h10'],
  abajo: ['m6 9 6 6 6-6'],
  mas: ['M12 5v14', 'M5 12h14'],
  descargar: ['M12 4v11', 'M7.5 10.5 12 15l4.5-4.5', 'M5 19.5h14'],
  subir: ['M12 20V9', 'M7.5 13.5 12 9l4.5 4.5', 'M5 4.5h14'],
  gota: ['M12 3.5S18 9.9 18 14a6 6 0 0 1-12 0c0-4.1 6-10.5 6-10.5Z'],
  area: ['M4 8.5V5a1 1 0 0 1 1-1h3.5', 'M15.5 4H19a1 1 0 0 1 1 1v3.5', 'M20 15.5V19a1 1 0 0 1-1 1h-3.5', 'M8.5 20H5a1 1 0 0 1-1-1v-3.5'],
  listo: ['M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', 'm8.5 12.2 2.4 2.4 4.6-4.9'],
  ondas: ['M3 9c2 0 2-1.5 4.5-1.5S9.5 9 12 9s2.5-1.5 4.5-1.5S19 9 21 9', 'M3 14c2 0 2-1.5 4.5-1.5S9.5 14 12 14s2.5-1.5 4.5-1.5S19 14 21 14', 'M3 19c2 0 2-1.5 4.5-1.5S9.5 19 12 19s2.5-1.5 4.5-1.5S19 19 21 19'],
  letra: ['M4 19 9 5l5 14', 'M5.8 14h6.4', 'M15 19l3-8 3 8', 'M16 16.5h4'],
}
</script>

<template>
  <svg
    class="icono"
    :width="tam"
    :height="tam"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in ICONOS[nombre]" :key="i" :d="d" />
  </svg>
</template>
