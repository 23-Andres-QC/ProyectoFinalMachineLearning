<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import Confirmar from '../components/Confirmar.vue'
import { ESTADOS, area, fechaCorta, fechaHora } from '../formato'
import { sesion } from '../sesion'

const lista = ref([])
const cargando = ref(true)
const error = ref('')
const confirmar = ref(null)
const esAdmin = computed(() => sesion.usuario?.rol === 'administrador')
let sondeo

async function cargar() {
  clearTimeout(sondeo)
  try {
    lista.value = (await api('/evaluaciones')) || []
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    cargando.value = false
  }
  if (lista.value.some((e) => e.estado === 'en_cola' || e.estado === 'procesando')) sondeo = setTimeout(cargar, 8000)
}

async function reintentar(e) {
  try {
    await api(`/evaluaciones/${e.id}/reintentar`, { metodo: 'POST' })
    await cargar()
  } catch (err) {
    error.value = err.message
  }
}

async function eliminar(e) {
  const ok = await confirmar.value.preguntar({
    titulo: `¿Eliminar la evaluación #${e.id}?`,
    texto: 'Se borran también sus polígonos. No se puede deshacer.',
    aceptar: 'Eliminar',
    peligro: true,
  })
  if (!ok) return
  try {
    await api(`/evaluaciones/${e.id}`, { metodo: 'DELETE' })
    await cargar()
  } catch (err) {
    error.value = err.message
  }
}

onMounted(cargar)
onBeforeUnmount(() => clearTimeout(sondeo))
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <h1>Evaluaciones</h1>
      <RouterLink to="/" class="boton">Nueva evaluación</RouterLink>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="cargando" class="tenue">Cargando…</p>
    <div v-else-if="!lista.length" class="vacio">
      Aún no hay evaluaciones. <RouterLink to="/">Dibuja un área en el mapa</RouterLink> para empezar.
    </div>
    <div v-else class="tabla-contenedor">
      <table class="tabla">
        <thead>
          <tr>
            <th>#</th>
            <th>Lluvia</th>
            <th>Pasada (hora local)</th>
            <th v-if="esAdmin">Usuario</th>
            <th>Estado</th>
            <th class="num">Charcos</th>
            <th class="num">Agua</th>
            <th>Creada</th>
            <th><span class="oculto">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in lista" :key="e.id">
            <td>{{ e.id }}</td>
            <td>{{ fechaCorta(e.fecha_lluvia) }}</td>
            <td>{{ fechaCorta(e.hora_pasada) }} · pista {{ e.pista }}</td>
            <td v-if="esAdmin">{{ e.usuario }}</td>
            <td><span class="estado" :class="e.estado">{{ ESTADOS[e.estado] }}</span></td>
            <td class="num">{{ e.charcos ?? '—' }}</td>
            <td class="num">{{ area(e.area_agua_m2) }}</td>
            <td>{{ fechaHora(e.creado) }}</td>
            <td class="acciones-fila">
              <RouterLink :to="{ path: '/', query: { id: e.id } }">Ver en el mapa</RouterLink>
              <a v-if="e.estado === 'completado' && e.charcos" :href="`/api/evaluaciones/${e.id}/resultado.kml`" download>KML</a>
              <button v-if="e.estado === 'error'" type="button" class="boton-texto" @click="reintentar(e)">Reintentar</button>
              <button type="button" class="boton-texto peligro" @click="eliminar(e)">Eliminar</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <Confirmar ref="confirmar" />
  </div>
</template>
