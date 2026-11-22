<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../api'
import Confirmar from '../components/Confirmar.vue'
import Icono from '../components/Icono.vue'
import PasosProceso from '../components/PasosProceso.vue'
import { ESTADOS, area, fechaCorta, hoyEn, mm } from '../formato'
import { catalogo, guardarModelo, infoModelo, modeloGuardado, nombreModelo, predeterminado, usarSalud } from '../modelos'

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
// Evaluaciones del historial dibujadas en el mapa: al entrar ninguna, solo las que la persona pide ver
const visibles = shallowRef(new Set())
const lugarMarcado = ref('')
const avisoLimpio = ref('')
// Modelo con el que se evalúa: se recuerda en el navegador; si ya no está en el servicio, se usa el predeterminado
const modeloElegido = ref(modeloGuardado())

// Desde este zoom se dibuja cada charco; más lejos, cada evaluación es un marcador con su número de charcos.
// Desde ZOOM_SIN_PUNTOS los polígonos ya se ven solos y se quitan los puntos que los marcan.
const ZOOM_CHARCOS = 11
const ZOOM_SIN_PUNTOS = 17
const EN_CURSO = ['en_cola', 'procesando']
const COLOR = { charco: '#ff2d55', agua: '#1f6fff', evaluada: '#3ec7e6', fallida: '#ff9f0a', caja: '#ffd60a' }
const ESTILO_CHARCO = { color: COLOR.charco, weight: 1.2, fillColor: COLOR.charco, fillOpacity: 0.55 }
// Toda el agua que segmenta el modelo ese día (mar, ríos y charcos), en azul debajo de los charcos, como en el notebook 01
const ESTILO_AGUA = { color: COLOR.agua, weight: 0.8, fillColor: COLOR.agua, fillOpacity: 0.4 }
const ESTILO_AREA = {
  completado: { color: COLOR.evaluada, weight: 2, fillOpacity: 0.05 },
  en_curso: { color: COLOR.evaluada, weight: 2, dashArray: '4 4', fillOpacity: 0.04 },
  error: { color: COLOR.fallida, weight: 2, dashArray: '4 4', fillOpacity: 0.04 },
}

// Los objetos de Leaflet quedan fuera de la reactividad de Vue
let mapa, rectangulo, capaResultado, capaFoco, esquina, sondeo, sondeoHistorial, pin
let capaAreas, capaAgua, capaCharcos, capaPuntos, capaResumen
// El agua segmentada se pide aparte (puede pesar más que los charcos) y solo al dibujar la evaluación
const aguaPedida = new Map()
let generacionAgua = 0
let pedidoEvaluacion = 0
let pedidoHistorial = 0
let vivo = true

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
const modeloActual = computed(() => infoModelo(modeloElegido.value))
const gruposModelos = computed(() => {
  const grupos = []
  for (const m of catalogo.value) {
    const g = grupos.at(-1)?.familia === m.familia ? grupos.at(-1) : grupos[grupos.push({ familia: m.familia, modelos: [] }) - 1]
    g.modelos.push(m)
  }
  return grupos
})
// Los modelos de cambio comparan con el día seco previo: sin días secos de referencia no pueden evaluar esa pasada
const faltaReferencia = computed(() => modeloActual.value?.tipo === 'cambio' && !!pasada.value && !pasada.value.referencias?.length)
const avisosModelo = computed(() => {
  const m = salud.value?.modelo
  if (!m) return []
  if (!m.disponible) return ['El servicio del modelo no responde.']
  const lista = []
  if (!catalogo.value.length) lista.push('No hay modelos entrenados en hidrosar-modelo/modelos/.')
  if (!m.credenciales_earthdata) lista.push('Faltan las credenciales de NASA Earthdata en el .env.')
  if (faltaReferencia.value) {
    lista.push(`«${modeloActual.value.nombre}» necesita un día seco de referencia y esta pasada no tiene. Elige otro modelo.`)
  }
  return lista
})
const enCurso = computed(() => EN_CURSO.includes(evaluacion.value?.estado))
// Pasos que informa el modelo: carga, relieve, descargas (con MB en vivo), segmentación y polígonos
const pasos = computed(() => evaluacion.value?.progreso?.pasos || [])
const duracion = computed(() => {
  const s = pasos.value.reduce((t, p) => t + (p.segundos || 0), 0)
  return s ? (s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`) : ''
})
const metodo = computed(() => {
  const m = evaluacion.value?.metodo || ''
  const cambio = m.match(/^cambio_2canales_vs_(\d+)_referencias$/)
  if (cambio) {
    return cambio[1] === '1'
      ? 'cambio entre la lluvia y el día seco previo'
      : `cambio entre la lluvia y el día seco previo, alineados con ${cambio[1]} días secos`
  }
  if (m === 'sin_referencia') return 'solo el modelo (no hubo día seco de referencia)'
  const n = m.match(/^cambio_vs_(\d+)_referencias$/)
  if (!n) return m
  return n[1] === '1' ? 'U-Net y cambio frente al día seco' : `U-Net y cambio frente a ${n[1]} días secos`
})
const charcosAbiertos = computed(() =>
  (evaluacion.value?.resultado?.features || [])
    .map((f) => ({ charco: f.properties.charco, area_m2: f.properties.area_m2, geometria: f.geometry }))
    .sort((a, b) => b.area_m2 - a.area_m2),
)
const dibujadas = computed(() => historial.value.filter((h) => visibles.value.has(h.id)))
const abiertaVisible = computed(() => !!evaluacion.value && visibles.value.has(evaluacion.value.id))
const charcosDibujados = computed(
  () => dibujadas.value.reduce((s, h) => s + (h.charcos || 0), 0) || (abiertaVisible.value ? charcosAbiertos.value.length : 0),
)
const aguaDibujada = computed(
  () => dibujadas.value.some((h) => h.agua_total_m2 > 0) || (abiertaVisible.value && evaluacion.value.agua_total_m2 > 0),
)
const modeloDeCambio = computed(() => infoModelo(evaluacion.value?.modelo)?.tipo === 'cambio')
const leyenda = computed(() => {
  const estados = new Set(dibujadas.value.map((h) => h.estado))
  if (abiertaVisible.value) estados.add(evaluacion.value.estado)
  const items = []
  if (charcosDibujados.value) items.push({ clase: 'charco', texto: 'Agua de lluvia empozada (charcos)' })
  if (aguaDibujada.value) items.push({ clase: 'agua', texto: 'Agua segmentada por el modelo' })
  if (estados.has('completado')) items.push({ clase: 'evaluada', texto: 'Área evaluada' })
  if (EN_CURSO.some((e) => estados.has(e))) items.push({ clase: 'en-curso', texto: 'En proceso' })
  if (estados.has('error')) items.push({ clase: 'fallida', texto: 'Con error' })
  if (bbox.value) items.push({ clase: 'caja', texto: 'Área seleccionada' })
  if (lugarMarcado.value) items.push({ clase: 'pin', texto: lugarMarcado.value })
  return items
})

const km = (v) => v.toLocaleString('es-PE', { maximumFractionDigits: 1 })
const pct = (v) => (v == null ? '—' : `${Math.round(v)} %`)
const nCharcos = (n) => `${n ?? 0} ${n === 1 ? 'charco' : 'charcos'}`
const referencias = (p) =>
  (p?.referencias || []).map((r) => `${fechaCorta(r.hora_local.slice(0, 10))} (${mm(r.lluvia_72h_mm)} en 72 h)`).join(', ') || 'ninguno'
// las pasadas buscadas desde ahora traen un solo día seco; las evaluaciones viejas pueden guardar dos
const tituloReferencias = (p) => ((p?.referencias || []).length > 1 ? 'Días secos de referencia' : 'Día seco de referencia')
const limitesDe = (b) => L.latLngBounds([b[1], b[0]], [b[3], b[2]])
const bboxDe = (l) => [l.getWest(), l.getSouth(), l.getEast(), l.getNorth()].map((v) => Math.round(v * 1e6) / 1e6)

watch([bbox, fecha], () => {
  busqueda.value = null
})

watch(modeloElegido, (id) => {
  if (id) guardarModelo(id)
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
  for (const [nombre, z] of [['hs-areas', 402], ['hs-agua', 406], ['hs-charcos', 410], ['hs-seleccion', 415], ['hs-puntos', 420]]) {
    mapa.createPane(nombre).style.zIndex = z
  }
  capaAreas = L.layerGroup().addTo(mapa)
  capaAgua = L.layerGroup()
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
  usarSalud(salud.value)
  if (!catalogo.value.some((m) => m.id === modeloElegido.value)) modeloElegido.value = predeterminado.value
  // Al entrar no se dibuja nada del historial. Solo se dibuja lo que se pide: ?id viene de «Ver en el mapa» en Evaluaciones
  // y ?todas de «Ver todas en el mapa»; ?seguir es una evaluación recién enviada, que se sigue en el panel sin dibujarla
  const { id, seguir, todas, lat, lon, fecha: dia, lugar, ir } = route.query
  const numero = (v) => (typeof v === 'string' && /^\d+$/.test(v) ? Number(v) : null)
  const diaValido = /^\d{4}-\d{2}-\d{2}$/.test(dia || '') ? dia : ''
  const nombreLugar = typeof lugar === 'string' ? lugar.slice(0, 120) : ''
  if (numero(id)) {
    visibles.value = new Set([numero(id)])
    pintarHistorial()
    abrirEvaluacion(numero(id))
  } else if (numero(seguir)) abrirEvaluacion(numero(seguir))
  else if (todas !== undefined) {
    mostrarEnMapa(historial.value.map((h) => h.id))
    router.replace({ query: {} })
  } else if (lat && lon && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))) {
    if (ir) marcarLugar(Number(lat), Number(lon), nombreLugar, diaValido)
    else usarPunto(Number(lat), Number(lon), diaValido, nombreLugar)
    router.replace({ query: {} })
  }
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

// «Ir al lugar» desde Lluvias: acerca el mapa y deja un pin, sin área ni búsqueda
function marcarLugar(lat, lon, lugar, dia) {
  quitarPin()
  lugarMarcado.value = lugar || 'Lugar elegido'
  pin = L.marker([lat, lon], {
    icon: L.divIcon({ className: 'pin-lugar', html: '<b></b>', iconSize: [0, 0] }),
    keyboard: false,
    interactive: false,
  })
    .bindTooltip(contenido(lugarMarcado.value), { permanent: true, direction: 'top', offset: [0, -34] })
    .addTo(mapa)
  mapa.setView([lat, lon], 14)
  if (dia && dia >= '2025-07-30') fecha.value = dia
}

function quitarPin() {
  pin?.remove()
  pin = null
  lugarMarcado.value = ''
}

// --- Historial: todo lo procesado queda en la base de datos; en el mapa solo se dibuja lo que se elige ver ---

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
  for (const capa of [capaAreas, capaAgua, capaCharcos, capaPuntos, capaResumen]) capa.clearLayers()
  generacionAgua++
  // Del más antiguo al más reciente, para que lo último evaluado quede encima
  for (const h of [...historial.value].reverse()) {
    if (!visibles.value.has(h.id)) continue
    dibujarAgua(h)
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
  // Respaldo: la evaluación abierta y pedida en el mapa que todavía no llegó en el historial
  const e = evaluacion.value
  if (e && visibles.value.has(e.id) && e.estado === 'completado' && !historial.value.some((h) => h.id === e.id)) {
    mostrarResultado(e.resultado)
    dibujarAgua(e)
  } else quitarResultado()
}

// Agua segmentada de una evaluación: se pide una vez (la clave cambia si se vuelve a procesar) y se dibuja si sigue a la vista
function dibujarAgua(h) {
  if (!(h.agua_total_m2 > 0)) return
  const clave = `${h.id}:${h.agua_total_m2}`
  if (!aguaPedida.has(clave)) {
    aguaPedida.set(
      clave,
      api(`/evaluaciones/${h.id}/agua`).catch(() => {
        aguaPedida.delete(clave)
        return null
      }),
    )
  }
  const generacion = generacionAgua
  aguaPedida.get(clave).then((f) => {
    if (!vivo || generacion !== generacionAgua || !f?.geometry) return
    L.geoJSON(f.geometry, { pane: 'hs-agua', style: ESTILO_AGUA })
      .bindTooltip(contenido(`Agua segmentada · ${area(f.properties.area_m2)}`, `Evaluación #${h.id} · todo lo que el modelo marca como agua ese día`), {
        sticky: true,
      })
      .addTo(capaAgua)
  })
}

// Dibuja solo estas evaluaciones del historial y encuadra el mapa en ellas
function mostrarEnMapa(ids, { encuadrar = true } = {}) {
  avisoLimpio.value = ''
  visibles.value = new Set(ids)
  pintarHistorial()
  if (!encuadrar) return
  const limites = L.latLngBounds([])
  for (const h of historial.value) if (visibles.value.has(h.id)) limites.extend(limitesDe(h.bbox))
  if (!limites.isValid() && evaluacion.value && visibles.value.has(evaluacion.value.id)) limites.extend(limitesDe(evaluacion.value.bbox))
  if (limites.isValid()) mapa.fitBounds(limites, { padding: [40, 40], maxZoom: 15 })
}

// La evaluación abierta en el panel pasa a dibujarse cuando la persona pide verla (botón o lista de charcos)
function dibujarAbierta() {
  const e = evaluacion.value
  if (!e) return
  avisoLimpio.value = ''
  if (!visibles.value.has(e.id)) {
    visibles.value = new Set([e.id])
    pintarHistorial()
  }
  if (route.query.id !== String(e.id)) router.replace({ query: { id: e.id } })
}

function verAbiertaEnMapa() {
  if (charcosAbiertos.value.length) verCharcos()
  else if (evaluacion.value) {
    dibujarAbierta()
    mapa.fitBounds(limitesDe(evaluacion.value.bbox), { padding: [30, 30] })
  }
}

function ajustarAlZoom() {
  zoom.value = mapa.getZoom()
  const cerca = zoom.value >= ZOOM_CHARCOS
  for (const [capa, ver] of [
    [capaResumen, !cerca],
    [capaAgua, cerca],
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

// Clic en una evaluación dibujada en el mapa: la abre en el panel.
// Si ya estaba a la vista (por ejemplo, con «Ver todas en el mapa» de Evaluaciones), lo demás sigue dibujado.
async function abrir(id, { encuadrar = true } = {}) {
  if (dibujando.value) cancelarDibujo()
  error.value = ''
  avisoLimpio.value = ''
  if (!visibles.value.has(id)) {
    visibles.value = new Set([id])
    pintarHistorial()
  }
  if (evaluacion.value?.id === id) {
    if (route.query.id !== String(id)) router.replace({ query: { id } })
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
  dibujarAbierta()
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
  dibujarAbierta()
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
  avisoLimpio.value = ''
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
      datos: { busqueda_id: busqueda.value.busqueda_id, indice: indice.value, modelo: modeloActual.value?.id || '' },
    })
    busqueda.value = null
    // La evaluación nueva se sigue en el panel; en el mapa se dibuja solo si la persona lo pide
    router.replace({ query: { seguir: id } })
    await abrirEvaluacion(id, { encuadrar: false })
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
    else if (visibles.value.has(e.id) && !historial.value.some((h) => h.id === e.id)) pintarHistorial()
    if (!vivo || pedido !== pedidoEvaluacion) return
    if (terminoAhora && visibles.value.has(e.id) && charcosAbiertos.value.length) verCharcos()
    // Mientras procesa se consulta seguido para ver avanzar los pasos y los MB descargados
    if (EN_CURSO.includes(e.estado)) sondeo = setTimeout(() => abrirEvaluacion(e.id), e.estado === 'procesando' ? 2500 : 5000)
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
  if (route.query.id || route.query.seguir) router.replace({ query: {} })
}

// «Limpiar»: la evaluación ya está guardada en la base; se despeja el panel y el mapa para evaluar otra zona
function limpiar() {
  const id = evaluacion.value?.id
  const enProceso = enCurso.value
  if (dibujando.value) cancelarDibujo()
  reiniciarEvaluacion()
  bbox.value = null
  busqueda.value = null
  rectangulo?.remove()
  rectangulo = null
  lugares.value = null
  textoLugar.value = ''
  lugarSugerido.value = ''
  error.value = ''
  quitarPin()
  visibles.value = new Set()
  pintarHistorial()
  avisoLimpio.value = id
    ? `La evaluación #${id} quedó guardada en Evaluaciones${enProceso ? ' y sigue procesándose' : ''}. Ya puedes evaluar otra zona.`
    : 'Mapa limpio. Ya puedes evaluar otra zona.'
}
</script>

<template>
  <div class="mapa-vista">
    <aside class="panel">
      <p v-if="avisoLimpio" class="aviso exito" role="status">{{ avisoLimpio }}</p>
      <section class="paso paso-modelo">
        <label class="campo-modelo">
          <span class="titulo-modelo"><span class="numero-icono"><Icono nombre="modelo" :tam="16" /></span> Modelo</span>
          <select v-model="modeloElegido" :disabled="!catalogo.length">
            <option v-if="!catalogo.length" value="">Sin modelos disponibles</option>
            <optgroup v-for="g in gruposModelos" :key="g.familia" :label="g.familia">
              <option v-for="m in g.modelos" :key="m.id" :value="m.id">
                {{ m.nombre }}{{ m.id === predeterminado ? ' · predeterminado' : '' }}
              </option>
            </optgroup>
          </select>
        </label>
        <p v-if="modeloActual" class="ayuda">{{ modeloActual.descripcion }}</p>
      </section>
      <section class="paso">
        <div class="titulo-fila">
          <h2><span class="numero">1</span> Área a evaluar</h2>
          <button
            v-if="!evaluacion && (bbox || lugarMarcado || visibles.size)"
            type="button"
            class="boton-texto"
            @click="limpiar"
          >
            Limpiar mapa
          </button>
        </div>
        <p v-if="lugarMarcado" class="ayuda resaltada">
          El pin marca {{ lugarMarcado }}. Dibuja el área alrededor y busca la pasada de NISAR.
        </p>
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
              <span class="dato">{{ tituloReferencias(p) }}: {{ referencias(p) }}</span>
              <span v-if="p.aviso" class="dato alerta-texto">{{ p.aviso }}</span>
            </span>
          </label>
          <div v-if="avisosModelo.length" class="aviso alerta">
            <p v-for="a in avisosModelo" :key="a">{{ a }}</p>
          </div>
          <button type="button" class="boton ancho" :disabled="enviando || !pasada || faltaReferencia" @click="evaluar">
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
        <template v-if="evaluacion.estado === 'procesando'">
          <PasosProceso v-if="pasos.length" :pasos="pasos" aria-label="Avance de la evaluación" />
          <p v-else class="ayuda">Preparando la evaluación…</p>
          <p class="ayuda">Puede tardar varios minutos. Si sales o limpias, el resultado igual queda guardado en Evaluaciones.</p>
        </template>
        <template v-if="evaluacion.estado === 'error'">
          <p class="error">{{ evaluacion.mensaje }}</p>
          <PasosProceso v-if="pasos.length" :pasos="pasos" aria-label="Pasos hasta el error" />
          <button type="button" class="boton secundario" :disabled="reintentando" @click="reintentar">
            {{ reintentando ? 'Reintentando…' : 'Reintentar' }}
          </button>
        </template>
        <template v-if="evaluacion.estado === 'completado'">
          <p v-if="evaluacion.mensaje" class="aviso alerta" role="status">{{ evaluacion.mensaje }}</p>
          <div class="cifras">
            <div><strong>{{ evaluacion.charcos ?? 0 }}</strong><span>charcos</span></div>
            <div><strong>{{ area(evaluacion.area_agua_m2 ?? 0) }}</strong><span>agua de lluvia</span></div>
            <div><strong>{{ evaluacion.mb_descargados ?? '—' }} MB</strong><span>descargados</span></div>
          </div>
          <p v-if="evaluacion.agua_total_m2 != null" class="dato con-muestra">
            <i class="muestra agua" aria-hidden="true"></i>
            <span>Agua segmentada por el modelo: <strong>{{ area(evaluacion.agua_total_m2) }}</strong> (mar, ríos y charcos)</span>
          </p>
          <p v-else class="ayuda">
            {{
              modeloDeCambio
                ? 'Este modelo marca solo el agua nueva: no guarda una capa con toda el agua de ese día.'
                : 'Esta evaluación se hizo antes de que se guardara el agua segmentada. Para verla, haz una evaluación nueva.'
            }}
          </p>
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
          <p v-if="evaluacion.modelo" class="ayuda">Modelo: {{ nombreModelo(evaluacion.modelo) }}</p>
          <p class="ayuda">Método: {{ metodo }}</p>
          <details v-if="pasos.length" class="detalle-pasos">
            <summary>Pasos del proceso{{ duracion ? ` · ${duracion}` : '' }}</summary>
            <PasosProceso :pasos="pasos" />
          </details>
          <div v-if="evaluacion.charcos || evaluacion.agua_total_m2" class="fila">
            <a class="boton secundario" :href="`/api/evaluaciones/${evaluacion.id}/resultado.kml`" download>Descargar KML</a>
            <a class="boton secundario" :href="`/api/evaluaciones/${evaluacion.id}/resultado.geojson`" download>GeoJSON</a>
          </div>
          <p v-if="evaluacion.charcos || evaluacion.agua_total_m2" class="ayuda">
            Llevan los charcos y el agua segmentada. El KML se abre en Google Earth o se importa en Google My Maps.
          </p>
        </template>
        <div class="acciones-evaluacion">
          <button v-if="!abiertaVisible" type="button" class="boton secundario" @click="verAbiertaEnMapa">Ver en el mapa</button>
          <button type="button" class="boton" @click="limpiar">Limpiar y evaluar otra zona</button>
        </div>
        <p class="ayuda">
          {{ abiertaVisible ? 'Dibujada en el mapa.' : 'No se dibuja en el mapa hasta que lo pidas.' }} Al limpiar, la evaluación queda
          guardada en Evaluaciones.
        </p>
      </section>

      <p v-if="errorHistorial" class="error">{{ errorHistorial }}</p>
    </aside>

    <div class="mapa-contenedor" :class="{ dibujando }">
      <div ref="contenedor" class="mapa"></div>
      <div v-if="leyenda.length" class="leyenda">
        <span v-for="i in leyenda" :key="i.clase"><i class="muestra" :class="i.clase"></i> {{ i.texto }}</span>
        <span v-if="zoom < ZOOM_CHARCOS && dibujadas.some((h) => h.charcos || h.agua_total_m2 > 0)" class="pista-zoom">
          El número indica los charcos. Acerca el mapa para ver los charcos y el agua segmentada.
        </span>
      </div>
    </div>

    <Confirmar ref="confirmar">
      <dl v-if="pasada && medidas" class="resumen">
        <dt>Modelo</dt>
        <dd>{{ modeloActual?.nombre || 'el predeterminado' }}</dd>
        <dt>Área</dt>
        <dd>{{ km(medidas.ancho) }} × {{ km(medidas.alto) }} km ({{ km(medidas.area) }} km²)</dd>
        <dt>Pasada de lluvia</dt>
        <dd>{{ fechaCorta(pasada.hora_local) }} · pista {{ pasada.pista }} · {{ pasada.direccion }}</dd>
        <dt>{{ tituloReferencias(pasada) }}</dt>
        <dd>{{ referencias(pasada) }}</dd>
      </dl>
      <p class="ayuda">Se descarga de NISAR solo el recorte del área y se guardan solo los polígonos del agua.</p>
    </Confirmar>
  </div>
</template>
