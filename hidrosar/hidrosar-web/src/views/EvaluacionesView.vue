<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import { avisar } from '../avisos'
import Confirmar from '../components/Confirmar.vue'
import Icono from '../components/Icono.vue'
import { ESTADOS, area, fechaCorta, fechaHora } from '../formato'
import { cargarCatalogo, nombreModelo } from '../modelos'
import { sesion } from '../sesion'

const lista = ref([])
const cargando = ref(true)
const error = ref('')
const confirmar = ref(null)
const esAdmin = computed(() => sesion.usuario?.rol === 'administrador')
const filtro = reactive({ texto: '', estado: '', soloAgua: false })
const orden = reactive({ campo: 'creado', descendente: true })
let sondeo

const EN_CURSO = ['en_cola', 'procesando']
const COLUMNAS = [
  { campo: 'id', texto: '#', num: false },
  { campo: 'fecha_lluvia', texto: 'Lluvia y pasada', num: false },
  { campo: 'usuario', texto: 'Usuario', num: false, admin: true },
  { campo: 'estado', texto: 'Estado', num: false },
  { campo: 'charcos', texto: 'Charcos', num: true },
  { campo: 'area_agua_m2', texto: 'Agua', num: true },
  { campo: 'creado', texto: 'Creada', num: false },
]
const columnas = computed(() => COLUMNAS.filter((c) => !c.admin || esAdmin.value))

const resumen = computed(() => {
  const hechas = lista.value.filter((e) => e.estado === 'completado')
  return {
    total: lista.value.length,
    completadas: hechas.length,
    enCurso: lista.value.filter((e) => EN_CURSO.includes(e.estado)).length,
    charcos: hechas.reduce((s, e) => s + (e.charcos || 0), 0),
    agua: hechas.reduce((s, e) => s + (e.area_agua_m2 || 0), 0),
  }
})

const filas = computed(() => {
  const q = filtro.texto.trim().toLowerCase().replace(/^#/, '')
  let salida = lista.value.filter((e) => {
    if (filtro.estado === 'en_curso' ? !EN_CURSO.includes(e.estado) : filtro.estado && e.estado !== filtro.estado) return false
    if (filtro.soloAgua && !e.charcos) return false
    if (!q) return true
    return [String(e.id), e.usuario, e.fecha_lluvia, fechaCorta(e.fecha_lluvia), String(e.pista), nombreModelo(e.modelo)].some((v) =>
      (v || '').toLowerCase().includes(q),
    )
  })
  const { campo, descendente } = orden
  salida = [...salida].sort((a, b) => {
    const x = a[campo] ?? -Infinity
    const y = b[campo] ?? -Infinity
    const r = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'es')
    return descendente ? -r : r
  })
  return salida
})

function ordenarPor(campo) {
  if (orden.campo === campo) orden.descendente = !orden.descendente
  else Object.assign(orden, { campo, descendente: ['creado', 'fecha_lluvia', 'charcos', 'area_agua_m2', 'id'].includes(campo) })
}

function ariaOrden(campo) {
  if (orden.campo !== campo) return 'none'
  return orden.descendente ? 'descending' : 'ascending'
}

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
  if (lista.value.some((e) => EN_CURSO.includes(e.estado))) sondeo = setTimeout(cargar, lista.value.some((e) => e.estado === 'procesando') ? 4000 : 8000)
}

async function reintentar(e) {
  try {
    await api(`/evaluaciones/${e.id}/reintentar`, { metodo: 'POST' })
    avisar(`La evaluación #${e.id} volvió a la cola`)
    await cargar()
  } catch (err) {
    avisar(err.message, 'error', 7000)
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
    avisar(`Evaluación #${e.id} eliminada`)
    await cargar()
  } catch (err) {
    avisar(err.message, 'error', 7000)
  }
}

// CSV de lo que se ve en la tabla (con los filtros aplicados), con BOM para que Excel lea bien las tildes
function exportarCsv() {
  const cabecera = ['id', 'fecha_lluvia', 'pasada_hora_local', 'pista', 'modelo', 'usuario', 'estado', 'charcos', 'agua_m2', 'creada', 'oeste', 'sur', 'este', 'norte']
  const celda = (v) => {
    const t = v == null ? '' : String(v)
    return /[",;\n]/.test(t) ? `"${t.replaceAll('"', '""')}"` : t
  }
  const lineas = filas.value.map((e) =>
    [e.id, e.fecha_lluvia, e.hora_pasada, e.pista, nombreModelo(e.modelo), e.usuario, e.estado, e.charcos, e.area_agua_m2 == null ? '' : Math.round(e.area_agua_m2), e.creado, ...e.bbox]
      .map(celda)
      .join(','),
  )
  const blob = new Blob(['﻿' + [cabecera.join(','), ...lineas].join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const enlace = document.createElement('a')
  enlace.href = URL.createObjectURL(blob)
  enlace.download = `hidrosar_evaluaciones_${new Date().toISOString().slice(0, 10)}.csv`
  enlace.click()
  setTimeout(() => URL.revokeObjectURL(enlace.href), 1000)
  avisar(`Se exportaron ${filas.value.length} evaluaciones`)
}

function limpiarFiltros() {
  Object.assign(filtro, { texto: '', estado: '', soloAgua: false })
}

onMounted(() => {
  cargar()
  cargarCatalogo()
})
onBeforeUnmount(() => clearTimeout(sondeo))
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <div>
        <h1>Evaluaciones</h1>
        <p class="subtitulo">Historial de las áreas evaluadas con el radar NISAR.</p>
      </div>
      <div class="fila">
        <RouterLink v-if="lista.length" :to="{ path: '/', query: { todas: 1 } }" class="boton secundario">
          <Icono nombre="mapa" /> Ver todas en el mapa
        </RouterLink>
        <button v-if="filas.length" type="button" class="boton secundario" @click="exportarCsv">
          <Icono nombre="descargar" /> Exportar CSV
        </button>
        <RouterLink to="/" class="boton"><Icono nombre="mas" /> Nueva evaluación</RouterLink>
      </div>
    </div>

    <div v-if="!cargando && lista.length" class="kpis">
      <div class="kpi">
        <div class="kpi-icono"><Icono nombre="lista" :tam="20" /></div>
        <strong>{{ resumen.total }}</strong><span>evaluaciones</span>
      </div>
      <div class="kpi">
        <div class="kpi-icono verde"><Icono nombre="listo" :tam="20" /></div>
        <strong>{{ resumen.completadas }}</strong><span>completadas{{ resumen.enCurso ? ` · ${resumen.enCurso} en proceso` : '' }}</span>
      </div>
      <div class="kpi">
        <div class="kpi-icono rojo"><Icono nombre="gota" :tam="20" /></div>
        <strong>{{ resumen.charcos.toLocaleString('es-PE') }}</strong><span>charcos detectados</span>
      </div>
      <div class="kpi">
        <div class="kpi-icono celeste"><Icono nombre="ondas" :tam="20" /></div>
        <strong>{{ area(resumen.agua) }}</strong><span>de agua de lluvia</span>
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="cargando" class="tenue">Cargando…</p>
    <div v-else-if="!lista.length" class="vacio">
      <span class="vacio-icono"><Icono nombre="area" :tam="26" /></span>
      <strong>Aún no hay evaluaciones</strong>
      <span><RouterLink to="/">Dibuja un área en el mapa</RouterLink> para empezar.</span>
    </div>
    <template v-else>
      <form class="filtros tarjeta" role="search" @submit.prevent>
        <label>Buscar
          <input v-model="filtro.texto" type="search" placeholder="#, fecha, pista o usuario">
        </label>
        <label>Estado
          <select v-model="filtro.estado">
            <option value="">Todos</option>
            <option value="completado">Completado</option>
            <option value="en_curso">En proceso</option>
            <option value="error">Con error</option>
          </select>
        </label>
        <label class="casilla"><input v-model="filtro.soloAgua" type="checkbox"> Solo con agua</label>
        <p class="tenue" aria-live="polite">Mostrando {{ filas.length }} de {{ lista.length }}</p>
      </form>

      <div v-if="!filas.length" class="vacio">
        Ninguna evaluación cumple el filtro. <button type="button" class="boton-texto" @click="limpiarFiltros">Quitar filtros</button>
      </div>
      <div v-else class="tabla-contenedor">
        <table class="tabla">
          <thead>
            <tr>
              <th v-for="c in columnas" :key="c.campo" :class="{ num: c.num }" :aria-sort="ariaOrden(c.campo)">
                <button type="button" class="orden" :data-activo="orden.campo === c.campo" @click="ordenarPor(c.campo)">
                  {{ c.texto }}
                  <span class="flecha" aria-hidden="true">{{ orden.campo === c.campo && !orden.descendente ? '▲' : '▼' }}</span>
                </button>
              </th>
              <th><span class="oculto">Acciones</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in filas" :key="e.id">
              <td>{{ e.id }}</td>
              <td>
                <span class="dos-lineas">
                  {{ fechaCorta(e.fecha_lluvia) }}
                  <small class="tenue">pasada {{ fechaCorta(e.hora_pasada) }} · pista {{ e.pista }}</small>
                  <small v-if="e.modelo" class="tenue">{{ nombreModelo(e.modelo) }}</small>
                </span>
              </td>
              <td v-if="esAdmin">{{ e.usuario }}</td>
              <td>
                <span class="dos-lineas">
                  <span class="estado" :class="e.estado">{{ ESTADOS[e.estado] }}</span>
                  <small v-if="e.etapa" class="tenue etapa-fila">{{ e.estado === 'error' ? `Falló en: ${e.etapa}` : e.etapa }}</small>
                </span>
              </td>
              <td class="num">{{ e.charcos ?? '—' }}</td>
              <td class="num">{{ area(e.area_agua_m2) }}</td>
              <td>
                <span class="dos-lineas">
                  {{ fechaHora(e.creado).split(', ')[0] }}
                  <small class="tenue">{{ fechaHora(e.creado).split(', ')[1] }}</small>
                </span>
              </td>
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
    </template>
    <Confirmar ref="confirmar" />
  </div>
</template>
