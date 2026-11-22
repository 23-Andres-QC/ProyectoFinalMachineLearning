<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { fechaCorta, hoyEn, mm } from '../formato'

const CLAVE = 'hidrosar:filtros-lluvias'
const router = useRouter()
const hoy = hoyEn('America/Lima')

function haceDias(n) {
  const d = new Date(`${hoy}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

const regiones = ref([])
const filtros = reactive({ region: 'Tumbes', ciudad: '', desde: haceDias(90), hasta: hoy, minimo: 1 })
try {
  const guardados = JSON.parse(localStorage.getItem(CLAVE) || 'null')
  if (guardados) Object.assign(filtros, { region: guardados.region ?? 'Tumbes', ciudad: guardados.ciudad ?? '', minimo: guardados.minimo ?? 1 })
} catch {
  // sin almacenamiento del navegador: se usan los valores por defecto
}
const soloNisar = ref(false)
const orden = ref('fecha')
const cargando = ref(false)
const error = ref('')
const datos = ref(null)

const ciudades = computed(() => regiones.value.find((r) => r.region === filtros.region)?.ciudades || [])
const todoPeru = computed(() => !datos.value?.region)
const conNisar = computed(() => (datos.value?.eventos || []).filter((e) => e.nisar.length).length)
const eventos = computed(() => {
  let lista = datos.value?.eventos || []
  if (soloNisar.value) lista = lista.filter((e) => e.nisar.length)
  if (orden.value === 'lluvia') lista = [...lista].sort((a, b) => b.mm - a.mm || b.fecha.localeCompare(a.fecha))
  return lista
})

watch(
  () => filtros.region,
  () => {
    filtros.ciudad = ''
  },
)

async function buscar() {
  cargando.value = true
  error.value = ''
  const q = new URLSearchParams({ desde: filtros.desde, hasta: filtros.hasta, minimo: String(filtros.minimo) })
  if (filtros.region) q.set('region', filtros.region)
  if (filtros.region && filtros.ciudad) q.set('ciudad', filtros.ciudad)
  try {
    datos.value = await api(`/lluvias?${q}`)
    try {
      localStorage.setItem(CLAVE, JSON.stringify({ region: filtros.region, ciudad: filtros.ciudad, minimo: filtros.minimo }))
    } catch {
      // no se pudo recordar el filtro; no afecta la búsqueda
    }
  } catch (e) {
    error.value = e.message
  } finally {
    cargando.value = false
  }
}

// Abre el mapa con un área sugerida alrededor de la ciudad y la fecha de la pasada (o del día de lluvia)
function abrirEnMapa(e, pasada) {
  const fecha = pasada ? pasada.hora_local.slice(0, 10) : e.fecha
  router.push({ path: '/', query: { lat: e.lat, lon: e.lon, fecha, lugar: e.ciudad } })
}

onMounted(async () => {
  try {
    regiones.value = await api('/lluvias/regiones')
  } catch (e) {
    error.value = e.message
  }
  buscar()
})
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <h1>Lluvias en el Perú</h1>
    </div>
    <p class="ayuda">
      Lluvia diaria estimada por <strong>Open-Meteo</strong> (modelos meteorológicos, no pluviómetros), la misma fuente que usa la
      búsqueda de NISAR, en las capitales de región y ciudades principales. Para cada día se indica si NISAR pasó sobre la ciudad
      ese día o el siguiente: esas son las lluvias que se pueden evaluar.
    </p>

    <form class="filtros tarjeta" @submit.prevent="buscar">
      <label>Región
        <select v-model="filtros.region">
          <option value="">Todo el Perú</option>
          <option v-for="r in regiones" :key="r.region" :value="r.region">{{ r.region }}</option>
        </select>
      </label>
      <label>Ciudad
        <select v-model="filtros.ciudad" :disabled="!filtros.region">
          <option value="">Todas</option>
          <option v-for="c in ciudades" :key="c.nombre" :value="c.nombre">{{ c.nombre }}</option>
        </select>
      </label>
      <label>Desde
        <input v-model="filtros.desde" type="date" min="2025-07-30" :max="filtros.hasta" required>
      </label>
      <label>Hasta
        <input v-model="filtros.hasta" type="date" :min="filtros.desde" :max="hoy" required>
      </label>
      <label>Lluvia mínima (mm)
        <input v-model.number="filtros.minimo" type="number" min="0.1" max="500" step="0.1" required>
      </label>
      <button class="boton" :disabled="cargando">{{ cargando ? 'Buscando…' : 'Buscar' }}</button>
    </form>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="cargando" class="tenue">
      Consultando Open-Meteo y NISAR…{{ filtros.region ? '' : ' Todo el Perú puede tardar unos segundos.' }}
    </p>

    <template v-if="datos && !cargando">
      <div class="resumen-lluvias">
        <p>
          <strong>{{ datos.total }}</strong> días con lluvia de {{ datos.minimo_mm }} mm o más ·
          <strong>{{ conNisar }}</strong> con pasada de NISAR el mismo día o el siguiente
        </p>
        <div class="fila">
          <label class="casilla"><input v-model="soloNisar" type="checkbox"> Solo con pasada de NISAR</label>
          <label class="casilla">Ordenar por
            <select v-model="orden">
              <option value="fecha">Más recientes</option>
              <option value="lluvia">Más lluvia</option>
            </select>
          </label>
        </div>
      </div>
      <p v-if="datos.aviso" class="aviso alerta">{{ datos.aviso }}</p>
      <div v-if="!eventos.length" class="vacio">No hay días con lluvia que cumplan el filtro.</div>
      <div v-else class="tabla-contenedor">
        <table class="tabla">
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Ciudad</th>
              <th v-if="todoPeru">Región</th>
              <th class="num">Lluvia del día</th>
              <th class="num">Horas con lluvia</th>
              <th>Pasada de NISAR</th>
              <th><span class="oculto">Acciones</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in eventos" :key="`${e.fecha}/${e.region}/${e.ciudad}`">
              <td>{{ fechaCorta(e.fecha) }}</td>
              <td>{{ e.ciudad }}</td>
              <td v-if="todoPeru">{{ e.region }}</td>
              <td class="num">{{ mm(e.mm) }}</td>
              <td class="num">{{ e.horas ?? '—' }}</td>
              <td>
                <div v-for="p in e.nisar" :key="p.hora_local" class="pasada-lluvia">
                  <span>
                    {{ fechaCorta(p.hora_local) }}
                    <span class="tenue">· {{ p.dia === 'mismo' ? 'mismo día' : 'día siguiente' }} · pista {{ p.pista }}</span>
                  </span>
                  <button type="button" class="boton-texto" @click="abrirEnMapa(e, p)">Evaluar</button>
                </div>
                <span v-if="!e.nisar.length" class="tenue">—</span>
              </td>
              <td class="acciones-fila">
                <button type="button" class="boton-texto" @click="abrirEnMapa(e)">Ver en el mapa</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>
