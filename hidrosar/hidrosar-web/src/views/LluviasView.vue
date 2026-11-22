<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { avisar } from '../avisos'
import GraficoLluvia from '../components/GraficoLluvia.vue'
import { fechaCorta, hoyEn, mm } from '../formato'
import { sesion } from '../sesion'

const CLAVE = 'hidrosar:filtros-lluvias'
const CLAVE_FUENTE = 'hidrosar:fuente-lluvias'
const INICIO_SENAMHI = '2024-01-01'
const router = useRouter()
const hoy = hoyEn('America/Lima')
const esAdmin = computed(() => sesion.usuario?.rol === 'administrador')

function haceDias(n) {
  const d = new Date(`${hoy}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

// "SAN JUAN DE LURIGANCHO" -> "San Juan de Lurigancho"
const MENORES = new Set(['de', 'del', 'la', 'las', 'los', 'y'])
function titulo(texto) {
  return (texto || '')
    .toLocaleLowerCase('es-PE')
    .split(' ')
    .map((p, i) => (i > 0 && MENORES.has(p) ? p : p.charAt(0).toLocaleUpperCase('es-PE') + p.slice(1)))
    .join(' ')
}

const fuente = ref('senamhi')
try {
  if (localStorage.getItem(CLAVE_FUENTE) === 'openmeteo') fuente.value = 'openmeteo'
} catch {
  // sin almacenamiento del navegador: se empieza por el Senamhi
}

// --- Open-Meteo: lluvia estimada por modelos en las ciudades principales ---

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
const eventos = computed(() => ordenar(datos.value?.eventos || []))

// --- Senamhi: lluvia medida cada hora por las estaciones automáticas ---

const estaciones = ref([])
const filtrosS = reactive({ estacion: '', desde: haceDias(90), hasta: hoy, minimo: 0.1 })
const cargandoS = ref(false)
const errorS = ref('')
const datosS = ref(null)
const conNisarS = computed(() => (datosS.value?.eventos || []).filter((e) => e.nisar.length).length)
const eventosS = computed(() => ordenar(datosS.value?.eventos || []))
const conDato = computed(() => estaciones.value.filter((e) => e.horas_con_dato > 0))

const entrada = ref(null)
const subiendo = ref(false)
const subida = ref(null)
const errorSubida = ref('')
const resumenSubida = computed(() => {
  const lista = subida.value?.archivos || []
  const bien = lista.filter((a) => !a.error)
  return {
    bien: bien.length,
    horas: bien.reduce((s, a) => s + a.horas, 0),
    estaciones: new Set(bien.map((a) => a.estacion)).size,
    fallas: lista.filter((a) => a.error),
  }
})

function ordenar(lista) {
  let salida = lista
  if (soloNisar.value) salida = salida.filter((e) => e.nisar.length)
  if (orden.value === 'lluvia') salida = [...salida].sort((a, b) => b.mm - a.mm || b.fecha.localeCompare(a.fecha))
  return salida
}

watch(
  () => filtros.region,
  () => {
    filtros.ciudad = ''
  },
)

watch(fuente, (f) => {
  try {
    localStorage.setItem(CLAVE_FUENTE, f)
  } catch {
    // no se pudo recordar la fuente; no afecta la consulta
  }
  if (f === 'senamhi' && !datosS.value && !cargandoS.value) buscarSenamhi()
  if (f === 'openmeteo' && !datos.value && !cargando.value) buscar()
})

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

async function cargarEstaciones() {
  try {
    estaciones.value = (await api('/lluvias/senamhi/estaciones')) || []
  } catch (e) {
    errorS.value = e.message
  }
}

async function buscarSenamhi() {
  cargandoS.value = true
  errorS.value = ''
  const q = new URLSearchParams({ desde: filtrosS.desde, hasta: filtrosS.hasta, minimo: String(filtrosS.minimo) })
  if (filtrosS.estacion) q.set('estacion', filtrosS.estacion)
  try {
    datosS.value = await api(`/lluvias/senamhi?${q}`)
  } catch (e) {
    errorS.value = e.message
  } finally {
    cargandoS.value = false
  }
}

async function subirTablas() {
  const archivos = [...(entrada.value?.files || [])]
  if (!archivos.length) return
  const formulario = new FormData()
  for (const a of archivos) formulario.append('archivos', a)
  subiendo.value = true
  errorSubida.value = ''
  subida.value = null
  try {
    subida.value = await api('/lluvias/senamhi/tablas', { metodo: 'POST', datos: formulario })
    entrada.value.value = ''
    const { bien, fallas } = resumenSubida.value
    if (bien) avisar(`${bien} ${bien === 1 ? 'tabla cargada' : 'tablas cargadas'}${fallas.length ? ` · ${fallas.length} con error` : ''}`)
    else avisar('No se pudo cargar ninguna tabla', 'error', 7000)
    await cargarEstaciones()
    await buscarSenamhi()
  } catch (e) {
    errorSubida.value = e.message
  } finally {
    subiendo.value = false
  }
}

// «Evaluar» / «Buscar en NISAR»: el mapa abre con un área sugerida alrededor del punto y busca la pasada
function abrirEnMapa(lat, lon, lugar, fecha) {
  router.push({ path: '/', query: { lat, lon, fecha, lugar } })
}

// «Ir al lugar»: el mapa solo se acerca al punto y lo marca con un pin
function irAlLugar(lat, lon, lugar, fecha) {
  router.push({ path: '/', query: { lat, lon, lugar, fecha, ir: '1' } })
}

const diaDe = (p) => p.hora_local.slice(0, 10)
const nombreEstacion = (e) => `estación ${titulo(e.estacion ?? e.nombre)}`

onMounted(async () => {
  await Promise.allSettled([
    api('/lluvias/regiones').then((r) => (regiones.value = r)),
    cargarEstaciones(),
  ])
  if (fuente.value === 'senamhi') buscarSenamhi()
  else buscar()
})
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <div>
        <h1>Lluvias en el Perú</h1>
        <p class="subtitulo">Días de lluvia y las pasadas de NISAR que sirven para evaluarlos.</p>
      </div>
      <div class="selector-fuente" role="group" aria-label="Fuente de los datos de lluvia">
        <button type="button" :aria-pressed="fuente === 'senamhi'" @click="fuente = 'senamhi'">Estaciones del Senamhi</button>
        <button type="button" :aria-pressed="fuente === 'openmeteo'" @click="fuente = 'openmeteo'">Ciudades (Open-Meteo)</button>
      </div>
    </div>

    <!-- Senamhi -->
    <template v-if="fuente === 'senamhi'">
      <p class="ayuda">
        Lluvia medida cada hora por las estaciones automáticas del <strong>Senamhi</strong> en Lima (tablas horarias de su portal de
        datos). Se suma la lluvia de cada día por estación y se indica si NISAR pasó sobre la estación ese día o el siguiente.
        <template v-if="conDato.length">
          Hay datos de {{ conDato.length }} de {{ estaciones.length }} estaciones.
        </template>
      </p>

      <form class="filtros tarjeta" @submit.prevent="buscarSenamhi">
        <label>Estación
          <select v-model="filtrosS.estacion">
            <option value="">Todas</option>
            <option v-for="e in estaciones" :key="e.codigo" :value="e.codigo" :disabled="!e.horas_con_dato">
              {{ titulo(e.nombre) }}{{ e.horas_con_dato ? '' : ' (sin datos de lluvia)' }}
            </option>
          </select>
        </label>
        <label>Desde
          <input v-model="filtrosS.desde" type="date" :min="INICIO_SENAMHI" :max="filtrosS.hasta" required>
        </label>
        <label>Hasta
          <input v-model="filtrosS.hasta" type="date" :min="filtrosS.desde" :max="hoy" required>
        </label>
        <label>Lluvia mínima (mm)
          <input v-model.number="filtrosS.minimo" type="number" min="0.1" max="500" step="0.1" required>
        </label>
        <button class="boton" :disabled="cargandoS">{{ cargandoS ? 'Buscando…' : 'Buscar' }}</button>
      </form>

      <details v-if="estaciones.length" class="tarjeta estaciones">
        <summary>Estaciones cargadas ({{ estaciones.length }})</summary>
        <div class="tabla-contenedor">
          <table class="tabla">
            <thead>
              <tr>
                <th>Estación</th>
                <th>Distrito</th>
                <th>Código</th>
                <th>Datos de lluvia</th>
                <th class="num">Horas con dato</th>
                <th><span class="oculto">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in estaciones" :key="e.codigo">
                <td>{{ titulo(e.nombre) }}</td>
                <td>{{ titulo(e.distrito) }}</td>
                <td class="tenue">{{ e.codigo }}</td>
                <td>
                  <template v-if="e.desde">{{ fechaCorta(e.desde) }} – {{ fechaCorta(e.hasta) }}</template>
                  <span v-else class="tenue">sin datos de lluvia</span>
                </td>
                <td class="num">{{ e.horas_con_dato.toLocaleString('es-PE') }}</td>
                <td class="acciones-fila">
                  <button type="button" class="boton-texto" @click="irAlLugar(e.lat, e.lon, nombreEstacion(e))">Ir al lugar</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>

      <form v-if="esAdmin" class="tarjeta subir-tablas" @submit.prevent="subirTablas">
        <label>Subir tablas horarias del Senamhi (.csv)
          <input ref="entrada" type="file" accept=".csv,text/csv" multiple required>
        </label>
        <button class="boton secundario" :disabled="subiendo">{{ subiendo ? 'Subiendo…' : 'Subir tablas' }}</button>
        <p class="ayuda">Las horas que ya estaban se actualizan; no se duplican.</p>
        <p v-if="errorSubida" class="error" role="alert">{{ errorSubida }}</p>
        <div v-if="subida" class="aviso" :class="resumenSubida.fallas.length ? 'alerta' : 'exito'" role="status">
          <p>
            {{ resumenSubida.bien }} {{ resumenSubida.bien === 1 ? 'tabla cargada' : 'tablas cargadas' }} de
            {{ resumenSubida.estaciones }} {{ resumenSubida.estaciones === 1 ? 'estación' : 'estaciones' }} ·
            {{ resumenSubida.horas.toLocaleString('es-PE') }} horas
          </p>
          <p v-for="f in resumenSubida.fallas" :key="f.archivo">{{ f.archivo }}: {{ f.error }}</p>
        </div>
      </form>

      <p v-if="errorS" class="error" role="alert">{{ errorS }}</p>
      <p v-if="cargandoS" class="tenue">Consultando las estaciones y NISAR…</p>

      <template v-if="datosS && !cargandoS">
        <div class="resumen-lluvias">
          <p>
            <strong>{{ datosS.total }}</strong> días con lluvia de {{ datosS.minimo_mm }} mm o más ·
            <strong>{{ conNisarS }}</strong> con pasada de NISAR el mismo día o el siguiente
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
        <p v-if="datosS.aviso" class="aviso alerta">{{ datosS.aviso }}</p>
        <GraficoLluvia
          v-if="datosS.eventos.length"
          :desde="datosS.desde"
          :hasta="datosS.hasta"
          :eventos="datosS.eventos"
          :estaciones="estaciones"
          :titulo="titulo"
        />
        <div v-if="!eventosS.length" class="vacio">No hay días con lluvia que cumplan el filtro.</div>
        <div v-else class="tabla-contenedor">
          <table class="tabla">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Estación</th>
                <th class="num">Lluvia del día</th>
                <th class="num">Horas con lluvia</th>
                <th class="num">Máx. en 1 h</th>
                <th>Pasada de NISAR</th>
                <th><span class="oculto">Acciones</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in eventosS" :key="`${e.fecha}/${e.codigo}`">
                <td>{{ fechaCorta(e.fecha) }}</td>
                <td>
                  <span class="dos-lineas">
                    {{ titulo(e.estacion) }}
                    <small v-if="titulo(e.distrito) !== titulo(e.estacion)" class="tenue">{{ titulo(e.distrito) }}</small>
                  </span>
                </td>
                <td class="num">{{ mm(e.mm) }}</td>
                <td class="num">
                  <span class="dos-lineas">
                    {{ e.horas_lluvia }}
                    <small v-if="e.horas_con_dato < 24" class="tenue">{{ e.horas_con_dato }}/24 h con dato</small>
                  </span>
                </td>
                <td class="num">{{ mm(e.max_hora_mm) }}</td>
                <td>
                  <div v-for="p in e.nisar" :key="p.hora_local" class="pasada-lluvia">
                    <span class="dos-lineas">
                      {{ fechaCorta(p.hora_local) }}
                      <small class="tenue">{{ p.dia === 'mismo' ? 'mismo día' : 'día siguiente' }} · pista {{ p.pista }}</small>
                    </span>
                    <button type="button" class="boton-texto" @click="abrirEnMapa(e.lat, e.lon, nombreEstacion(e), diaDe(p))">
                      Evaluar
                    </button>
                  </div>
                  <span v-if="!e.nisar.length" class="tenue">—</span>
                </td>
                <td class="acciones-fila">
                  <button type="button" class="boton-texto" @click="irAlLugar(e.lat, e.lon, nombreEstacion(e), e.fecha)">
                    Ir al lugar
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>

    <!-- Open-Meteo -->
    <template v-else>
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
                    <span class="dos-lineas">
                      {{ fechaCorta(p.hora_local) }}
                      <small class="tenue">{{ p.dia === 'mismo' ? 'mismo día' : 'día siguiente' }} · pista {{ p.pista }}</small>
                    </span>
                    <button type="button" class="boton-texto" @click="abrirEnMapa(e.lat, e.lon, e.ciudad, diaDe(p))">Evaluar</button>
                  </div>
                  <span v-if="!e.nisar.length" class="tenue">—</span>
                </td>
                <td class="acciones-fila">
                  <button type="button" class="boton-texto" @click="irAlLugar(e.lat, e.lon, e.ciudad, e.fecha)">Ir al lugar</button>
                  <button type="button" class="boton-texto" @click="abrirEnMapa(e.lat, e.lon, e.ciudad, e.fecha)">Buscar en NISAR</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </div>
</template>
