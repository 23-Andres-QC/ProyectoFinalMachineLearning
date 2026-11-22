<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../api'
import Confirmar from '../components/Confirmar.vue'
import { ESTADOS, area, fechaCorta, hoyEn, mm } from '../formato'
import { sesion } from '../sesion'

const route = useRoute()
const router = useRouter()

const contenedor = ref(null)
const confirmar = ref(null)
const salud = ref(null)
const bbox = ref(null)
const dibujando = ref(false)
const fecha = ref(hoyEn('America/Lima'))
const buscando = ref(false)
const busqueda = ref(null)
const indice = ref(0)
const error = ref('')
const enviando = ref(false)
const evaluacion = shallowRef(null)
const textoLugar = ref('')
const lugares = ref(null)
const buscandoLugar = ref(false)
const lugarSugerido = ref('')
const reintentando = ref(false)
const historial = shallowRef([])
const errorHistorial = ref('')
const charcoElegido = ref(null)
const zoom = ref(5)

// Desde este zoom se dibuja cada charco; más lejos, cada evaluación es un marcador con su número de charcos.
// Desde ZOOM_SIN_PUNTOS los polígonos ya se ven solos y se quitan los puntos que los marcan.
const ZOOM_CHARCOS = 11
const ZOOM_SIN_PUNTOS = 17
const EN_CURSO = ['en_cola', 'procesando']
const COLOR = { charco: '#ff2d55', evaluada: '#3ec7e6', fallida: '#ff9f0a', caja: '#ffd60a' }
const ESTILO_CHARCO = { color: COLOR.charco, weight: 1.2, fillColor: COLOR.charco, fillOpacity: 0.55 }
const ESTILO_AREA = {
  completado: { color: COLOR.evaluada, weight: 2, fillOpacity: 0.05 },
  en_curso: { color: COLOR.evaluada, weight: 2, dashArray: '4 4', fillOpacity: 0.04 },
  error: { color: COLOR.fallida, weight: 2, dashArray: '4 4', fillOpacity: 0.04 },
}

// Los objetos de Leaflet quedan fuera de la reactividad de Vue
let mapa, rectangulo, capaResultado, capaFoco, esquina, sondeo, sondeoHistorial
let capaAreas, capaCharcos, capaPuntos, capaResumen
let pedidoEvaluacion = 0
let pedidoHistorial = 0
let vivo = true

const esAdmin = computed(() => sesion.usuario?.rol === 'administrador')
const zona = computed(() => salud.value?.zona_horaria || 'America/Lima')
const hoy = computed(() => hoyEn(zona.value))
const maxArea = computed(() => salud.value?.max_area_km2 || 150)
const medidas = computed(() => {
  if (!bbox.value) return null
  const [o, s, e, n] = bbox.value
  const ancho = (e - o) * 111.32 * Math.cos((((s + n) / 2) * Math.PI) / 180)
  const alto = (n - s) * 110.57
  return { ancho, alto, area: ancho * alto }
})
const problemaArea = computed(() => {
  const m = medidas.value
  if (!m) return ''
  if (m.ancho < 1 || m.alto < 1) return 'El área debe medir al menos 1 km por lado'
  if (m.area > maxArea.value) return `El área supera el máximo de ${maxArea.value} km²`
  return ''
})
const pasada = computed(() => busqueda.value?.pasadas?.[indice.value] || null)
const cercanas = computed(() =>
  [
    { nombre: 'Anterior', pasada: busqueda.value?.anterior },
    { nombre: 'Siguiente', pasada: busqueda.value?.siguiente },
  ].filter((c) => c.pasada),
)
const avisosModelo = computed(() => {
  const m = salud.value?.modelo
  if (!m) return []
  if (!m.disponible) return ['El servicio del modelo no responde.']
  const lista = []
  if (!m.modelo_encontrado) lista.push(`Falta el modelo entrenado (${m.modelo}) en hidrosar-modelo/modelos/.`)
  if (!m.credenciales_earthdata) lista.push('Faltan las credenciales de NASA Earthdata en el .env.')
  return lista
})
const enCurso = computed(() => EN_CURSO.includes(evaluacion.value?.estado))
const metodo = computed(() => {
  const m = evaluacion.value?.metodo || ''
  if (m === 'sin_referencia') return 'solo U-Net (no hubo día seco de referencia)'
  const n = m.match(/^cambio_vs_(\d+)_referencias$/)
  return n ? `U-Net y cambio frente a ${n[1]} día(s) seco(s)` : m
})
const charcosAbiertos = computed(() =>
  (evaluacion.value?.resultado?.features || [])
    .map((f) => ({ charco: f.properties.charco, area_m2: f.properties.area_m2, geometria: f.geometry }))
    .sort((a, b) => b.area_m2 - a.area_m2),
)
const recientes = computed(() => historial.value.slice(0, 8))
const totales = computed(() => {
  const hechas = historial.value.filter((h) => h.estado === 'completado')
  return {
    charcos: hechas.reduce((s, h) => s + (h.charcos || 0), 0),
    agua: hechas.reduce((s, h) => s + (h.area_agua_m2 || 0), 0),
  }
})
const leyenda = computed(() => {
  const estados = new Set(historial.value.map((h) => h.estado))
  const items = []
  if (totales.value.charcos || charcosAbiertos.value.length) items.push({ clase: 'charco', texto: 'Agua de lluvia empozada' })
  if (estados.has('completado')) items.push({ clase: 'evaluada', texto: 'Área evaluada' })
  if (EN_CURSO.some((e) => estados.has(e))) items.push({ clase: 'en-curso', texto: 'En proceso' })
  if (estados.has('error')) items.push({ clase: 'fallida', texto: 'Con error' })
  if (bbox.value) items.push({ clase: 'caja', texto: 'Área seleccionada' })
  return items
})

const km = (v) => v.toLocaleString('es-PE', { maximumFractionDigits: 1 })
const pct = (v) => (v == null ? '—' : `${Math.round(v)} %`)
const nCharcos = (n) => `${n ?? 0} ${n === 1 ? 'charco' : 'charcos'}`
const referencias = (p) =>
  (p?.referencias || []).map((r) => `${fechaCorta(r.hora_local.slice(0, 10))} (${mm(r.lluvia_72h_mm)} en 72 h)`).join(', ') || 'ninguno'
const limitesDe = (b) => L.latLngBounds([b[1], b[0]], [b[3], b[2]])
const bboxDe = (l) => [l.getWest(), l.getSouth(), l.getEast(), l.getNorth()].map((v) => Math.round(v * 1e6) / 1e6)

watch([bbox, fecha], () => {
  busqueda.value = null
})

onMounted(async () => {
  mapa = L.map(contenedor.value, { minZoom: 3 }).setView([-9.5, -75.5], 5)
  const satelite = L.layerGroup([
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: 'Imágenes © Esri, Maxar, Earthstar Geographics',
    }),
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
    }),
  ])
  const calles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© colaboradores de OpenStreetMap',
  })
  satelite.addTo(mapa)
  L.control.layers({ Satélite: satelite, Calles: calles }, null, { position: 'topright' }).addTo(mapa)
  L.control.scale({ imperial: false }).addTo(mapa)

  // Capas en orden: áreas abajo, luego los charcos, el área seleccionada y encima los puntos que marcan cada charco
  for (const [nombre, z] of [['hs-areas', 402], ['hs-charcos', 410], ['hs-seleccion', 415], ['hs-puntos', 420]]) {
    mapa.createPane(nombre).style.zIndex = z
  }
  capaAreas = L.layerGroup().addTo(mapa)
  capaCharcos = L.layerGroup()
  capaPuntos = L.layerGroup()
  capaResumen = L.layerGroup()
  mapa.on('click', alHacerClic)
  mapa.on('mousemove', alMover)
  mapa.on('zoomend', ajustarAlZoom)
  ajustarAlZoom()
  window.addEventListener('keydown', alTeclear)

  const [estado] = await Promise.allSettled([api('/salud'), cargarHistorial()])
  if (!vivo) return
  salud.value = estado.status === 'fulfilled' ? estado.value : null
  const { id, lat, lon, fecha: dia, lugar } = route.query
  if (id) abrirEvaluacion(id)
  else if (Number.isFinite(Number(lat)) && Number.isFinite(Number(lon)) && lat && lon) {
    usarPunto(Number(lat), Number(lon), /^\d{4}-\d{2}-\d{2}$/.test(dia || '') ? dia : '', typeof lugar === 'string' ? lugar : '')
    router.replace({ query: {} })
  } else verHistorial()
})

onBeforeUnmount(() => {
  vivo = false
  clearTimeout(sondeo)
  clearTimeout(sondeoHistorial)
  window.removeEventListener('keydown', alTeclear)
  mapa?.remove()
})

// Viene de la lista de lluvias: área sugerida de unos 6.6 × 6.6 km alrededor de la ciudad y búsqueda en NISAR
function usarPunto(lat, lon, dia, lugar) {
  const dLat = 0.03
  const dLon = 0.03 / Math.cos((lat * Math.PI) / 180)
  const b = [lon - dLon, lat - dLat, lon + dLon, lat + dLat].map((v) => Math.round(v * 1e6) / 1e6)
  bbox.value = b
  ponerRectangulo(limitesDe(b))
  mapa.fitBounds(limitesDe(b), { padding: [30, 30] })
  lugarSugerido.value = lugar || 'el punto elegido'
  if (dia) {
    fecha.value = dia
    buscarNisar()
  }
}

// --- Historial: todo lo procesado queda en la base de datos y se dibuja en el mapa al entrar ---

async function cargarHistorial() {
  clearTimeout(sondeoHistorial)
  const pedido = ++pedidoHistorial
  try {
    const lista = (await api('/historial')) || []
    if (!vivo || pedido !== pedidoHistorial) return
    historial.value = lista
    errorHistorial.value = ''
    pintarHistorial()
  } catch (e) {
    if (!vivo || pedido !== pedidoHistorial) return
    errorHistorial.value = `No se pudo cargar el historial: ${e.message}`
  }
  if (historial.value.some((h) => EN_CURSO.includes(h.estado))) sondeoHistorial = setTimeout(cargarHistorial, 15000)
}

function pintarHistorial() {
  for (const capa of [capaAreas, capaCharcos, capaPuntos, capaResumen]) capa.clearLayers()
  // Del más antiguo al más reciente, para que lo último evaluado quede encima
  for (const h of [...historial.value].reverse()) {
    const limites = limitesDe(h.bbox)
    // El área ya está a la vista: se abre sin mover el mapa. El marcador (mapa lejos) además acerca hasta el área.
    L.rectangle(limites, { pane: 'hs-areas', ...ESTILO_AREA[EN_CURSO.includes(h.estado) ? 'en_curso' : h.estado] })
      .on('click', () => !dibujando.value && abrir(h.id, { encuadrar: false }))
      .addTo(capaAreas)
    L.marker(limites.getCenter(), { icon: iconoEvaluacion(h), bubblingMouseEvents: true })
      .bindTooltip(contenido(`Evaluación #${h.id} · ${ESTADOS[h.estado]}`, detalleEvaluacion(h)), { direction: 'top', offset: [0, -16] })
      .on('click', () => !dibujando.value && abrir(h.id))
      .addTo(capaResumen)
    for (const c of h.lista_charcos) {
      const elegir = () => !dibujando.value && elegirCharco(h, c)
      const texto = () => contenido(`Charco ${c.charco} · ${area(c.area_m2)}`, `Evaluación #${h.id} · lluvia del ${fechaCorta(h.fecha_lluvia)}`)
      L.geoJSON(c.geometria, { pane: 'hs-charcos', style: ESTILO_CHARCO })
        .bindTooltip(texto(), { sticky: true })
        .on('click', elegir)
        .addTo(capaCharcos)
      L.circleMarker([c.centro[1], c.centro[0]], {
        pane: 'hs-puntos',
        radius: 7,
        color: '#ffffff',
        weight: 2,
        fillColor: COLOR.charco,
        fillOpacity: 1,
      })
        .bindTooltip(texto(), { direction: 'top', offset: [0, -8] })
        .on('click', elegir)
        .addTo(capaPuntos)
    }
  }
  if (evaluacion.value && historial.value.some((h) => h.id === evaluacion.value.id)) quitarResultado()
}

function ajustarAlZoom() {
  zoom.value = mapa.getZoom()
  const cerca = zoom.value >= ZOOM_CHARCOS
  for (const [capa, ver] of [
    [capaResumen, !cerca],
    [capaCharcos, cerca],
    [capaPuntos, cerca && zoom.value < ZOOM_SIN_PUNTOS],
  ]) {
    if (ver) capa.addTo(mapa)
    else capa.remove()
  }
}

// Los textos de los tooltips van como nodos de texto, nunca como HTML
function contenido(titulo, detalle) {
  const nodo = document.createElement('div')
  const fuerte = document.createElement('strong')
  fuerte.textContent = titulo
  nodo.append(fuerte)
  if (detalle) nodo.append(document.createElement('br'), detalle)
  return nodo
}

function detalleEvaluacion(h) {
  const lluvia = `Lluvia del ${fechaCorta(h.fecha_lluvia)}`
  if (h.estado === 'completado') return `${lluvia} · ${h.charcos ? `${nCharcos(h.charcos)}, ${area(h.area_agua_m2)}` : 'sin agua empozada'}`
  if (h.estado === 'error') return `${lluvia} · clic para ver el detalle`
  return lluvia
}

function iconoEvaluacion(h) {
  const n = Number(h.charcos) || 0
  const [clase, marca] =
    h.estado === 'completado' ? [n ? 'con-agua' : 'sin-agua', String(n)] : h.estado === 'error' ? ['fallida', '!'] : ['en-curso', '…']
  return L.divIcon({
    className: `marca-evaluacion ${clase}`,
    html: `<b><span aria-hidden="true">${marca}</span><span class="oculto">Evaluación ${Number(h.id)}</span></b>`,
    iconSize: [0, 0],
  })
}

function verHistorial() {
  const limites = L.latLngBounds([])
  for (const h of historial.value) limites.extend(limitesDe(h.bbox))
  if (limites.isValid()) mapa.fitBounds(limites, { padding: [40, 40], maxZoom: 13 })
}

async function abrir(id, { encuadrar = true } = {}) {
  if (dibujando.value) cancelarDibujo()
  error.value = ''
  if (evaluacion.value?.id === id) {
    if (encuadrar) mapa.fitBounds(limitesDe(evaluacion.value.bbox), { padding: [30, 30] })
    return
  }
  router.replace({ query: { id } })
  await abrirEvaluacion(id, { encuadrar })
}

async function elegirCharco(h, c) {
  await abrir(h.id, { encuadrar: false })
  acercarA(c)
}

function acercarA(c) {
  quitarFoco()
  charcoElegido.value = c.charco
  capaFoco = L.geoJSON(c.geometria, {
    pane: 'hs-seleccion',
    interactive: false,
    style: { color: '#ffffff', weight: 3, fill: false },
  }).addTo(mapa)
  mapa.fitBounds(capaFoco.getBounds(), { padding: [80, 80], maxZoom: 18 })
}

function verCharcos() {
  const limites = L.latLngBounds([])
  for (const c of charcosAbiertos.value) limites.extend(L.geoJSON(c.geometria).getBounds())
  if (limites.isValid()) mapa.fitBounds(limites, { padding: [60, 60], maxZoom: 17 })
}

function quitarFoco() {
  capaFoco?.remove()
  capaFoco = null
  charcoElegido.value = null
}

// --- Dibujo del rectángulo: un clic en una esquina y otro en la opuesta (funciona igual con el dedo) ---

function empezarDibujo() {
  reiniciarEvaluacion()
  error.value = ''
  lugarSugerido.value = ''
  dibujando.value = true
  esquina = null
  mapa.doubleClickZoom.disable()
}

function alHacerClic(e) {
  if (!dibujando.value) return
  if (!esquina) {
    esquina = e.latlng
    ponerRectangulo(L.latLngBounds(esquina, esquina))
    return
  }
  const limites = L.latLngBounds(esquina, e.latlng)
  ponerRectangulo(limites)
  terminarDibujo()
  bbox.value = bboxDe(limites)
}

function alMover(e) {
  if (dibujando.value && esquina) rectangulo.setBounds(L.latLngBounds(esquina, e.latlng))
}

function terminarDibujo() {
  dibujando.value = false
  esquina = null
  setTimeout(() => mapa?.doubleClickZoom.enable(), 300)
}

function cancelarDibujo() {
  terminarDibujo()
  if (bbox.value) ponerRectangulo(limitesDe(bbox.value))
  else if (rectangulo) {
    rectangulo.remove()
    rectangulo = null
  }
}

function alTeclear(e) {
  if (e.key === 'Escape' && dibujando.value) cancelarDibujo()
}

function ponerRectangulo(limites) {
  if (rectangulo) rectangulo.setBounds(limites)
  else {
    rectangulo = L.rectangle(limites, {
      pane: 'hs-seleccion',
      color: COLOR.caja,
      weight: 2.5,
      dashArray: '6 4',
      fillOpacity: 0.06,
      interactive: false,
    })
    rectangulo.addTo(mapa)
  }
}

// --- Búsqueda de lugares (OpenStreetMap Nominatim) ---

async function buscarLugar() {
  const q = textoLugar.value.trim()
  if (!q) return
  buscandoLugar.value = true
  lugares.value = null
  try {
    const r = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&accept-language=es&q=${encodeURIComponent(q)}`)
    lugares.value = r.ok ? await r.json() : []
  } catch {
    lugares.value = []
  } finally {
    buscandoLugar.value = false
  }
}

function irA(lugar) {
  const [s, n, o, e] = lugar.boundingbox.map(Number)
  mapa.fitBounds([[s, o], [n, e]], { maxZoom: 13 })
  lugares.value = null
}

// --- NISAR y evaluación ---

async function buscarNisar() {
  error.value = ''
  buscando.value = true
  busqueda.value = null
  indice.value = 0
  try {
    busqueda.value = await api('/nisar/buscar', { metodo: 'POST', datos: { bbox: bbox.value, fecha: fecha.value } })
  } catch (e) {
    error.value = e.message
  } finally {
    buscando.value = false
  }
}

function irAFecha(p) {
  fecha.value = p.hora_local.slice(0, 10)
  buscarNisar()
}

async function evaluar() {
  if (!(await confirmar.value.preguntar({ titulo: 'Confirmar evaluación', aceptar: 'Evaluar' }))) return
  enviando.value = true
  error.value = ''
  try {
    const { id } = await api('/evaluaciones', {
      metodo: 'POST',
      datos: { busqueda_id: busqueda.value.busqueda_id, indice: indice.value },
    })
    busqueda.value = null
    router.replace({ query: { id } })
    await abrirEvaluacion(id)
  } catch (e) {
    error.value = e.message
    if (e.estado === 410) busqueda.value = null
  } finally {
    enviando.value = false
  }
}

async function abrirEvaluacion(id, { encuadrar = true } = {}) {
  clearTimeout(sondeo)
  const pedido = ++pedidoEvaluacion
  try {
    const e = await api(`/evaluaciones/${id}`)
    if (!vivo || pedido !== pedidoEvaluacion) return
    const antes = evaluacion.value
    const otra = antes?.id !== e.id
    const terminoAhora = !otra && EN_CURSO.includes(antes.estado) && !EN_CURSO.includes(e.estado)
    evaluacion.value = e
    if (otra) {
      quitarResultado()
      quitarFoco()
      bbox.value = e.bbox
      fecha.value = e.fecha_lluvia
      lugarSugerido.value = ''
      ponerRectangulo(limitesDe(e.bbox))
      if (encuadrar) mapa.fitBounds(limitesDe(e.bbox), { padding: [30, 30] })
    }
    // Una evaluación nueva, reintentada o recién terminada todavía no está así en el historial: se recarga
    if (historial.value.find((h) => h.id === e.id)?.estado !== e.estado) await cargarHistorial()
    if (!vivo || pedido !== pedidoEvaluacion) return
    if (e.estado === 'completado' && !historial.value.some((h) => h.id === e.id)) mostrarResultado(e.resultado)
    if (terminoAhora && charcosAbiertos.value.length) verCharcos()
    if (EN_CURSO.includes(e.estado)) sondeo = setTimeout(() => abrirEvaluacion(e.id), 5000)
  } catch (err) {
    if (vivo && pedido === pedidoEvaluacion) error.value = err.message
  }
}

async function reintentar() {
  reintentando.value = true
  error.value = ''
  try {
    await api(`/evaluaciones/${evaluacion.value.id}/reintentar`, { metodo: 'POST' })
    await abrirEvaluacion(evaluacion.value.id)
  } catch (e) {
    error.value = e.message
  } finally {
    reintentando.value = false
  }
}

// Respaldo por si la evaluación abierta no vino en el historial (por ejemplo, si falló su carga)
function mostrarResultado(geojson) {
  quitarResultado()
  if (!geojson?.features?.length) return
  capaResultado = L.geoJSON(geojson, {
    pane: 'hs-charcos',
    style: ESTILO_CHARCO,
    onEachFeature: (f, capa) => capa.bindTooltip(contenido(`Charco ${f.properties.charco} · ${area(f.properties.area_m2)}`), { sticky: true }),
  }).addTo(mapa)
}

function quitarResultado() {
  capaResultado?.remove()
  capaResultado = null
}

function reiniciarEvaluacion() {
  clearTimeout(sondeo)
  pedidoEvaluacion++
  evaluacion.value = null
  quitarResultado()
  quitarFoco()
  if (route.query.id) router.replace({ query: {} })
}
</script>

<template>
  <div class="mapa-vista">
    <aside class="panel">
      <section class="paso">
        <h2><span class="numero">1</span> Área a evaluar</h2>
        <form class="fila" role="search" @submit.prevent="buscarLugar">
          <input v-model="textoLugar" type="search" placeholder="Buscar ciudad o lugar" aria-label="Buscar ciudad o lugar">
          <button class="boton secundario" :disabled="buscandoLugar">Ir</button>
        </form>
        <ul v-if="lugares?.length" class="lugares">
          <li v-for="l in lugares" :key="l.place_id">
            <button type="button" @click="irA(l)">{{ l.display_name }}</button>
          </li>
        </ul>
        <p v-else-if="lugares" class="ayuda">No se encontró ese lugar.</p>

        <button v-if="!dibujando" type="button" class="boton ancho" @click="empezarDibujo">
          {{ bbox ? 'Dibujar otra área' : 'Dibujar rectángulo en el mapa' }}
        </button>
        <template v-else>
          <p class="ayuda resaltada">Haz clic en una esquina del área y luego en la esquina opuesta. <kbd>Esc</kbd> cancela.</p>
          <button type="button" class="boton secundario ancho" @click="cancelarDibujo">Cancelar dibujo</button>
        </template>
        <p v-if="medidas && !dibujando" class="medidas">
          {{ km(medidas.ancho) }} × {{ km(medidas.alto) }} km · <strong>{{ km(medidas.area) }} km²</strong>
        </p>
        <p v-if="lugarSugerido && medidas && !dibujando" class="ayuda">
          Área sugerida alrededor de {{ lugarSugerido }}. Si quieres otra, dibújala.
        </p>
        <p v-if="problemaArea && !dibujando" class="error">{{ problemaArea }}</p>
        <p v-if="!bbox && !dibujando" class="ayuda">Entre 1 km por lado y {{ maxArea }} km² en total.</p>
      </section>

      <section class="paso" :class="{ apagado: !bbox || problemaArea || dibujando }">
        <h2><span class="numero">2</span> Fecha de la lluvia</h2>
        <form class="fila" @submit.prevent="buscarNisar">
          <input v-model="fecha" type="date" :max="hoy" min="2025-07-30" required aria-label="Fecha de la lluvia">
          <button class="boton" :disabled="!bbox || !!problemaArea || dibujando || buscando || !fecha">
            {{ buscando ? 'Buscando…' : 'Buscar en NISAR' }}
          </button>
        </form>
        <p class="ayuda">Día en hora local ({{ zona }}).</p>
      </section>

      <section v-if="busqueda" class="paso">
        <p class="aviso" :class="busqueda.encontrada ? 'exito' : 'alerta'" role="status">{{ busqueda.mensaje }}</p>
        <template v-if="busqueda.encontrada">
          <p v-if="busqueda.pasadas.length > 1" class="ayuda">NISAR pasó {{ busqueda.pasadas.length }} veces ese día; elige una.</p>
          <label v-for="(p, i) in busqueda.pasadas" :key="p.inicio_utc" class="pasada" :class="{ elegida: i === indice }">
            <input v-model="indice" type="radio" name="pasada" :value="i">
            <span>
              <strong>{{ fechaCorta(p.hora_local) }}</strong> <span class="tenue">hora local</span>
              <span class="dato">Pista {{ p.pista }} · {{ p.direccion }} · {{ p.cuadros.length }} cuadro(s)</span>
              <span class="dato">Cobertura del área: {{ pct(p.cobertura_pct) }}</span>
              <span class="dato">Lluvia previa: {{ mm(p.lluvia_24h_mm) }} en 24 h · {{ mm(p.lluvia_72h_mm) }} en 72 h</span>
              <span class="dato">Días secos de referencia: {{ referencias(p) }}</span>
              <span v-if="p.aviso" class="dato alerta-texto">{{ p.aviso }}</span>
            </span>
          </label>
          <div v-if="avisosModelo.length" class="aviso alerta">
            <p v-for="a in avisosModelo" :key="a">{{ a }}</p>
          </div>
          <button type="button" class="boton ancho" :disabled="enviando || !pasada" @click="evaluar">
            {{ enviando ? 'Enviando…' : 'Evaluar esta pasada' }}
          </button>
        </template>
        <template v-else>
          <div v-for="c in cercanas" :key="c.nombre" class="cercana">
            <span>{{ c.nombre }}: <strong>{{ fechaCorta(c.pasada.hora_local) }}</strong> · pista {{ c.pasada.pista }}</span>
            <button type="button" class="boton-texto" @click="irAFecha(c.pasada)">Buscar ese día</button>
          </div>
          <p v-if="!cercanas.length" class="ayuda">NISAR no pasó sobre esta área en las semanas cercanas.</p>
        </template>
      </section>

      <p v-if="error" class="error" role="alert">{{ error }}</p>

      <section v-if="evaluacion" class="paso">
        <h2><span class="numero">3</span> Evaluación #{{ evaluacion.id }}</h2>
        <p class="estado" :class="evaluacion.estado">
          <span v-if="enCurso" class="girando" aria-hidden="true"></span>
          {{ ESTADOS[evaluacion.estado] }}
        </p>
        <p class="dato">
          Lluvia del {{ fechaCorta(evaluacion.fecha_lluvia) }} · pasada {{ fechaCorta(evaluacion.pasada?.hora_local) }} (pista
          {{ evaluacion.pasada?.pista }})
        </p>
        <p v-if="evaluacion.estado === 'en_cola'" class="ayuda">Esperando turno: se procesa una evaluación a la vez.</p>
        <p v-if="evaluacion.estado === 'procesando'" class="ayuda">
          Descargando el recorte de NISAR y segmentando. Puede tardar varios minutos. Si sales, el resultado igual queda guardado y
          aparece en el mapa.
        </p>
        <template v-if="evaluacion.estado === 'error'">
          <p class="error">{{ evaluacion.mensaje }}</p>
          <button type="button" class="boton secundario" :disabled="reintentando" @click="reintentar">
            {{ reintentando ? 'Reintentando…' : 'Reintentar' }}
          </button>
        </template>
        <template v-if="evaluacion.estado === 'completado'">
          <div class="cifras">
            <div><strong>{{ evaluacion.charcos ?? 0 }}</strong><span>charcos</span></div>
            <div><strong>{{ area(evaluacion.area_agua_m2 ?? 0) }}</strong><span>agua de lluvia</span></div>
            <div><strong>{{ evaluacion.mb_descargados ?? '—' }} MB</strong><span>descargados</span></div>
          </div>
          <p v-if="!evaluacion.charcos" class="ayuda">No se detectó agua de lluvia empozada en el área.</p>
          <div v-if="charcosAbiertos.length" class="subseccion">
            <div class="titulo-fila">
              <h3>Charcos detectados</h3>
              <button type="button" class="boton-texto" @click="verCharcos">Ver todos</button>
            </div>
            <ol class="lista-mapa">
              <li v-for="c in charcosAbiertos" :key="c.charco">
                <button
                  type="button"
                  :class="{ elegido: c.charco === charcoElegido }"
                  :aria-pressed="c.charco === charcoElegido"
                  @click="acercarA(c)"
                >
                  <i class="muestra charco" aria-hidden="true"></i>
                  <span>Charco {{ c.charco }}</span>
                  <span class="tenue">{{ area(c.area_m2) }}</span>
                </button>
              </li>
            </ol>
            <p class="ayuda">Elige un charco para acercarte a él.</p>
          </div>
          <p class="ayuda">Método: {{ metodo }}</p>
          <div v-if="evaluacion.charcos" class="fila">
            <a class="boton secundario" :href="`/api/evaluaciones/${evaluacion.id}/resultado.kml`" download>Descargar KML</a>
            <a class="boton secundario" :href="`/api/evaluaciones/${evaluacion.id}/resultado.geojson`" download>GeoJSON</a>
          </div>
          <p v-if="evaluacion.charcos" class="ayuda">El KML se abre en Google Earth o se importa en Google My Maps.</p>
        </template>
        <button type="button" class="boton-texto" @click="reiniciarEvaluacion">Cerrar evaluación</button>
      </section>

      <section class="paso">
        <div class="titulo-fila">
          <h2>Historial guardado</h2>
          <button v-if="historial.length" type="button" class="boton-texto" @click="verHistorial">Ver todo en el mapa</button>
        </div>
        <p v-if="errorHistorial" class="error">{{ errorHistorial }}</p>
        <p v-else-if="!historial.length" class="ayuda">
          Aún no hay evaluaciones. Todo lo que proceses queda guardado aquí y dibujado en el mapa.
        </p>
        <template v-if="historial.length">
          <p class="dato">
            {{ historial.length }} {{ historial.length === 1 ? 'evaluación' : 'evaluaciones' }} · {{ nCharcos(totales.charcos) }} ·
            {{ area(totales.agua) }} de agua
          </p>
          <ul class="lista-mapa">
            <li v-for="h in recientes" :key="h.id">
              <button type="button" :class="{ elegido: h.id === evaluacion?.id }" @click="abrir(h.id)">
                <span>
                  #{{ h.id }} · lluvia {{ fechaCorta(h.fecha_lluvia) }}<template v-if="esAdmin"> · {{ h.usuario }}</template>
                </span>
                <span class="estado" :class="h.estado">
                  {{ h.estado === 'completado' ? nCharcos(h.charcos) : ESTADOS[h.estado] }}
                </span>
              </button>
            </li>
          </ul>
          <RouterLink v-if="historial.length > recientes.length" to="/evaluaciones" class="ayuda">
            Ver las {{ historial.length }} evaluaciones
          </RouterLink>
          <p class="ayuda">Se guarda en la base de datos: lo verás cada vez que entres.</p>
        </template>
      </section>
    </aside>

    <div class="mapa-contenedor" :class="{ dibujando }">
      <div ref="contenedor" class="mapa"></div>
      <div v-if="leyenda.length" class="leyenda">
        <span v-for="i in leyenda" :key="i.clase"><i class="muestra" :class="i.clase"></i> {{ i.texto }}</span>
        <span v-if="zoom < ZOOM_CHARCOS && totales.charcos" class="pista-zoom">
          El número indica los charcos. Acerca el mapa para verlos.
        </span>
      </div>
    </div>

    <Confirmar ref="confirmar">
      <dl v-if="pasada && medidas" class="resumen">
        <dt>Área</dt>
        <dd>{{ km(medidas.ancho) }} × {{ km(medidas.alto) }} km ({{ km(medidas.area) }} km²)</dd>
        <dt>Pasada de lluvia</dt>
        <dd>{{ fechaCorta(pasada.hora_local) }} · pista {{ pasada.pista }} · {{ pasada.direccion }}</dd>
        <dt>Días secos de referencia</dt>
        <dd>{{ referencias(pasada) }}</dd>
      </dl>
      <p class="ayuda">Se descarga de NISAR solo el recorte del área y se guardan solo los polígonos del agua.</p>
    </Confirmar>
  </div>
</template>
