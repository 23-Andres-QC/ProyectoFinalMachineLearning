<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { avisar } from '../avisos'
import Icono from '../components/Icono.vue'
import { fechaCorta } from '../formato'
import { sesion } from '../sesion'

const datos = ref({ servicio: true, escenas: [], modelos: [], validaciones: [] })
const cargando = ref(true)
const error = ref('')
const filtro = reactive({ escena: '', familia: '' })
const esAdmin = computed(() => sesion.usuario?.rol === 'administrador')
let sondeo

const ESTADOS_VALIDACION = { pendiente: 'En cola', procesando: 'Procesando', completado: 'Lista', error: 'Error' }
const EN_CURSO = ['pendiente', 'procesando']

const modelos = computed(() => new Map(datos.value.modelos.map((m) => [m.id, m])))
const familias = computed(() => [...new Set(datos.value.modelos.map((m) => m.familia))])

// Solo las validaciones de los modelos del catálogo (Vol1 y ModelosVol3); si el servicio no responde, todas las guardadas
const vigentes = computed(() =>
  datos.value.modelos.length ? datos.value.validaciones.filter((v) => modelos.value.has(v.modelo)) : datos.value.validaciones,
)
const listas = computed(() => vigentes.value.filter((v) => v.estado === 'completado').length)
const enCurso = computed(() => vigentes.value.find((v) => v.estado === 'procesando'))

const escenas = computed(() => {
  const porEscena = new Map()
  for (const v of vigentes.value) {
    if (!porEscena.has(v.escena)) porEscena.set(v.escena, [])
    porEscena.get(v.escena).push(v)
  }
  const conocidas = datos.value.escenas.length
    ? datos.value.escenas
    : [...porEscena.keys()].map((clave) => ({ clave, lugar: clave, disponible: true }))
  return conocidas
    .filter((e) => !filtro.escena || e.clave === filtro.escena)
    .map((e) => {
      const filas = (porEscena.get(e.clave) || []).filter((v) => !filtro.familia || familiaDe(v) === filtro.familia)
      const grupos = []
      for (const v of filas) {
        const familia = familiaDe(v)
        let g = grupos.find((x) => x.familia === familia)
        if (!g) grupos.push((g = { familia, filas: [] }))
        g.filas.push(v)
      }
      for (const g of grupos) g.filas.sort((a, b) => nombre(a).localeCompare(nombre(b), 'es'))
      grupos.sort((a, b) => a.familia.localeCompare(b.familia, 'es'))
      return { ...e, grupos, vacia: !filas.length }
    })
})

const familiaDe = (v) => modelos.value.get(v.modelo)?.familia || 'Otros'
const nombre = (v) => modelos.value.get(v.modelo)?.nombre || v.modelo.split('/').pop()
const sinCambio = (e) => e.cambio === false && datos.value.modelos.some((m) => m.tipo === 'cambio')
const titulo = (e) => (e.fecha ? `${e.lugar} · ${fechaCorta(e.fecha)}` : e.lugar)
const nombreEscena = (clave) => {
  const e = datos.value.escenas.find((x) => x.clave === clave)
  return e ? titulo(e) : clave
}

async function cargar() {
  clearTimeout(sondeo)
  try {
    datos.value = await api('/validaciones')
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    cargando.value = false
  }
  if (vigentes.value.some((v) => EN_CURSO.includes(v.estado))) sondeo = setTimeout(cargar, 15000)
}

async function recalcular(v) {
  try {
    await api(`/validaciones/${v.id}/recalcular`, { metodo: 'POST' })
    avisar(`«${nombre(v)}» volvió a la cola`)
    await cargar()
  } catch (err) {
    avisar(err.message, 'error', 7000)
  }
}

onMounted(cargar)
onBeforeUnmount(() => clearTimeout(sondeo))
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <div>
        <h1>Validaciones</h1>
        <p class="subtitulo">
          El mejor modelo de cada grupo (Vol1 y ModelosVol3), corrido en las zonas de validación de los notebooks. Elige uno para
          ver en el mapa dónde acierta, dónde marca agua de más y dónde se le escapa.
        </p>
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="cargando" class="tenue">Cargando…</p>
    <template v-else>
      <p v-if="!datos.servicio" class="aviso alerta" role="status">
        El servicio del modelo no responde: se muestran las validaciones ya guardadas.
      </p>
      <p v-if="vigentes.length" class="aviso" :class="listas === vigentes.length ? 'exito' : ''" role="status" aria-live="polite">
        {{ listas }} de {{ vigentes.length }} validaciones listas.
        <template v-if="listas < vigentes.length">
          Se calculan en segundo plano, una a la vez y después de las evaluaciones de los usuarios<template v-if="enCurso">
            (ahora: {{ nombre(enCurso) }} en {{ nombreEscena(enCurso.escena) }})</template>.
        </template>
      </p>

      <div v-if="!vigentes.length && !datos.escenas.length" class="vacio">
        <span class="vacio-icono"><Icono nombre="modelo" :tam="26" /></span>
        <strong>Aún no hay validaciones</strong>
        <span>Aparecen cuando el servicio del modelo está encendido.</span>
      </div>

      <template v-else>
        <form class="filtros tarjeta" @submit.prevent>
          <label>Zona
            <select v-model="filtro.escena">
              <option value="">Todas</option>
              <option v-for="e in datos.escenas" :key="e.clave" :value="e.clave">{{ titulo(e) }}</option>
            </select>
          </label>
          <label v-if="familias.length > 1">Modelos
            <select v-model="filtro.familia">
              <option value="">Todos</option>
              <option v-for="f in familias" :key="f" :value="f">{{ f }}</option>
            </select>
          </label>
        </form>

        <section v-for="e in escenas" :key="e.clave" class="tarjeta escena-validacion" :aria-labelledby="`escena-${e.clave}`">
          <h2 :id="`escena-${e.clave}`">{{ titulo(e) }}</h2>
          <p v-if="e.pista" class="tenue">
            {{ e.dia === 'seco' ? 'Día seco' : 'Día de lluvia' }} · pista {{ e.pista }}<template v-if="e.seco">
              · día seco de referencia {{ fechaCorta(e.seco) }}</template> · {{ e.origen }}
          </p>
          <!-- las ya calculadas se muestran aunque falten los recortes (por ejemplo, en un servidor sin Data/) -->
          <p v-if="e.vacia && !e.disponible" class="aviso alerta">Faltan los recortes NISAR de esta zona en Data/crudos_nisar.</p>
          <p v-else-if="e.vacia" class="ayuda">Ninguna validación con este filtro.</p>
          <div v-else class="tabla-contenedor">
            <table class="tabla">
              <thead>
                <tr>
                  <th scope="col">Modelo</th>
                  <th scope="col">Estado</th>
                  <th scope="col"><span class="oculto">Acciones</span></th>
                </tr>
              </thead>
              <tbody v-for="g in e.grupos" :key="g.familia">
                <tr class="fila-grupo">
                  <th colspan="3" scope="rowgroup">{{ g.familia }}</th>
                </tr>
                <tr v-for="v in g.filas" :key="v.id">
                  <td>{{ nombre(v) }}</td>
                  <td>
                    <span class="dos-lineas">
                      <span class="estado" :class="v.estado">
                        <span v-if="v.estado === 'procesando'" class="girando" aria-hidden="true"></span>
                        {{ ESTADOS_VALIDACION[v.estado] }}
                      </span>
                      <small v-if="v.estado === 'error' && v.mensaje" class="tenue">{{ v.mensaje }}</small>
                    </span>
                  </td>
                  <td class="acciones-fila">
                    <RouterLink v-if="v.estado === 'completado'" :to="{ path: '/', query: { validacion: v.id } }">Ver en el mapa</RouterLink>
                    <button
                      v-if="esAdmin && e.disponible && ['completado', 'error'].includes(v.estado)"
                      type="button"
                      class="boton-texto"
                      @click="recalcular(v)"
                    >
                      Recalcular
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="sinCambio(e)" class="ayuda">
            El ensamble de U-Net de cambio (Vol1) no se valida aquí: esta zona no tiene un día seco de la misma órbita.
          </p>
        </section>
      </template>
    </template>
  </div>
</template>
