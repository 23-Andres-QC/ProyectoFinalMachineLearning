<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fechaCorta, mm } from '../formato'

// Lluvia diaria por estación (una franja por estación) con las pasadas de NISAR marcadas bajo la línea base.
// Los datos son los mismos de la tabla de abajo, que sirve de vista accesible del gráfico.
const props = defineProps({
  desde: { type: String, required: true },
  hasta: { type: String, required: true },
  eventos: { type: Array, required: true },
  estaciones: { type: Array, required: true },
  titulo: { type: Function, required: true },
})

const contenedor = ref(null)
const ancho = ref(900)
const punto = ref(null)
// «propia»: cada franja llega hasta su día más lluvioso (se ve la garúa de todas las estaciones);
// «comun»: todas con la misma escala (se comparan cantidades entre estaciones)
const escala = ref('propia')
let observador

const IZQ = 168
const DER = 92
const FILA = 44
const TIRA = 12
const SEP = 14
const EJE = 26

onMounted(() => {
  observador = new ResizeObserver(([e]) => (ancho.value = Math.max(300, Math.floor(e.contentRect.width))))
  observador.observe(contenedor.value)
})
onBeforeUnmount(() => observador?.disconnect())

const dias = computed(() => {
  const lista = []
  const d = new Date(`${props.desde}T12:00:00Z`)
  const fin = new Date(`${props.hasta}T12:00:00Z`)
  while (d <= fin && lista.length < 400) {
    lista.push(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return lista
})
const indice = computed(() => new Map(dias.value.map((f, i) => [f, i])))
const estrecho = computed(() => ancho.value < 560)
const izq = computed(() => (estrecho.value ? 4 : IZQ))
const der = computed(() => (estrecho.value ? 4 : DER))
const paso = computed(() => (ancho.value - izq.value - der.value) / Math.max(1, dias.value.length))
const anchoBarra = computed(() => Math.max(1, paso.value - (paso.value > 5 ? 2 : paso.value > 2.5 ? 1 : 0)))
// en pantallas angostas el nombre va arriba de la franja
const cabezaFila = computed(() => (estrecho.value ? 20 : 0))
const altoFila = computed(() => cabezaFila.value + FILA)
const pasoFila = computed(() => altoFila.value + TIRA + SEP)

// el techo de la escala se redondea hacia arriba para que la barra más alta no toque el borde
const techoEscala = (m) => (m <= 2 ? Math.ceil(m * 10) / 10 : Math.ceil(m))
const maximoComun = computed(() => techoEscala(Math.max(0.1, ...props.eventos.map((e) => e.mm))))

const filas = computed(() => {
  const codigos = new Set(props.eventos.map((e) => e.codigo))
  return props.estaciones
    .filter((e) => codigos.has(e.codigo))
    .map((est, n) => {
      const delDia = new Map()
      const pasadas = new Map()
      for (const ev of props.eventos) {
        if (ev.codigo !== est.codigo) continue
        delDia.set(ev.fecha, ev)
        for (const p of ev.nisar) pasadas.set(p.hora_local.slice(0, 10), p)
      }
      const valores = [...delDia.values()].map((e) => e.mm)
      const total = Math.round(valores.reduce((s, v) => s + v, 0) * 10) / 10
      const maximo = Math.max(0, ...valores)
      return { est, delDia, pasadas, total, maximo, techo: techoEscala(Math.max(0.1, maximo)), y: n * pasoFila.value }
    })
})
const alto = computed(() => filas.value.length * pasoFila.value - SEP + EJE)

const xDe = (i) => izq.value + i * paso.value + (paso.value - anchoBarra.value) / 2
const hBarra = (v, fila) => {
  const tope = escala.value === 'comun' ? maximoComun.value : fila.techo
  return Math.max(1.5, (v / tope) * (FILA - 6))
}

const MESES = new Intl.DateTimeFormat('es-PE', { month: 'short', timeZone: 'UTC' })
const marcasMes = computed(() => {
  const marcas = []
  dias.value.forEach((f, i) => {
    if (i === 0 || f.endsWith('-01')) {
      const mes = MESES.format(new Date(`${f}T12:00:00Z`)).replace('.', '')
      const texto = i === 0 || f.slice(5, 7) === '01' ? `${mes} ${f.slice(0, 4)}` : mes
      marcas.push({ i, texto: texto.charAt(0).toLocaleUpperCase('es-PE') + texto.slice(1) })
    }
  })
  return marcas.filter((m, k) => k === 0 || (m.i - marcas[k - 1].i) * paso.value >= 52)
})

function alMover(evento, fila) {
  const caja = contenedor.value.getBoundingClientRect()
  const x = evento.clientX - caja.left
  const i = Math.floor((x - izq.value) / paso.value)
  const fecha = dias.value[i]
  if (!fecha) {
    punto.value = null
    return
  }
  // el cuadro se abre hacia el lado con más espacio para no tapar el puntero ni salirse del gráfico
  const aLaIzquierda = x > caja.width / 2
  punto.value = {
    fila,
    fecha,
    evento: fila.delDia.get(fecha),
    pasada: fila.pasadas.get(fecha),
    x: aLaIzquierda ? x - 14 : x + 14,
    aLaIzquierda,
    y: fila.y + altoFila.value + TIRA + 6,
    i,
  }
}
</script>

<template>
  <figure class="grafico-lluvia">
    <figcaption class="grafico-cabeza">
      <div>
        <h2>Lluvia diaria por estación</h2>
        <p class="ayuda">
          Del {{ fechaCorta(desde) }} al {{ fechaCorta(hasta) }} ·
          <template v-if="escala === 'comun'">misma escala en todas las franjas (la más alta llega a {{ mm(maximoComun) }})</template>
          <template v-else>cada franja llega hasta el día más lluvioso de su estación</template>
        </p>
      </div>
      <div class="grafico-controles">
        <ul class="leyenda-grafico">
          <li><i class="muestra-lluvia" aria-hidden="true"></i> Lluvia del día</li>
          <li><i class="muestra-nisar" aria-hidden="true"></i> Pasada de NISAR</li>
        </ul>
        <div class="selector-fuente chico" role="group" aria-label="Escala de las barras">
          <button type="button" :aria-pressed="escala === 'propia'" @click="escala = 'propia'">Escala por estación</button>
          <button type="button" :aria-pressed="escala === 'comun'" @click="escala = 'comun'">Misma escala</button>
        </div>
      </div>
    </figcaption>
    <div ref="contenedor" class="grafico-cuerpo" @mouseleave="punto = null">
      <svg
        :width="ancho"
        :height="alto"
        role="img"
        :aria-label="`Lluvia diaria de ${filas.length} estaciones del Senamhi entre el ${fechaCorta(desde)} y el ${fechaCorta(hasta)}. El detalle está en la tabla de abajo.`"
      >
        <g v-for="f in filas" :key="f.est.codigo" :transform="`translate(0 ${f.y})`">
          <text v-if="!estrecho" :x="izq - 12" :y="altoFila - 4" text-anchor="end" class="g-etiqueta">{{ titulo(f.est.nombre) }}</text>
          <text v-else :x="izq" y="13" class="g-etiqueta">
            {{ titulo(f.est.nombre) }}<tspan class="g-total" dx="8">{{ mm(f.total) }} en total · máx. {{ mm(f.maximo) }}</tspan>
          </text>
          <rect
            v-if="punto && punto.fila === f"
            :x="izq + punto.i * paso"
            :y="cabezaFila"
            :width="Math.max(paso, 2)"
            :height="FILA + TIRA"
            class="g-guia"
          />
          <rect
            v-for="[fecha, ev] in f.delDia"
            :key="fecha"
            :x="xDe(indice.get(fecha))"
            :y="altoFila - hBarra(ev.mm, f)"
            :width="anchoBarra"
            :height="hBarra(ev.mm, f)"
            :rx="anchoBarra >= 6 ? 2 : 0"
            class="g-barra"
          />
          <line :x1="izq" :x2="ancho - der" :y1="altoFila" :y2="altoFila" class="g-base" />
          <path
            v-for="[fecha] in f.pasadas"
            v-show="indice.has(fecha)"
            :key="`n${fecha}`"
            :d="`M${izq + (indice.get(fecha) + 0.5) * paso} ${altoFila + 2} l5 8 h-10 z`"
            class="g-nisar"
          />
          <template v-if="!estrecho">
            <text :x="ancho - der + 12" :y="altoFila - 18" class="g-total fuerte">{{ mm(f.total) }}</text>
            <text :x="ancho - der + 12" :y="altoFila - 3" class="g-total">máx. {{ mm(f.maximo) }}</text>
          </template>
          <rect
            :x="izq"
            :y="cabezaFila"
            :width="Math.max(0, ancho - izq - der)"
            :height="FILA + TIRA"
            class="g-zona"
            @mousemove="alMover($event, f)"
          />
        </g>
        <g :transform="`translate(0 ${alto - EJE + 6})`">
          <g v-for="m in marcasMes" :key="m.i">
            <line :x1="izq + m.i * paso" :x2="izq + m.i * paso" y1="-4" y2="2" class="g-base" />
            <text :x="izq + m.i * paso + 3" y="14" class="g-eje">{{ m.texto }}</text>
          </g>
          <text v-if="!estrecho" :x="ancho - der + 12" y="14" class="g-eje">en el periodo</text>
        </g>
      </svg>
      <div
        v-if="punto"
        class="g-tooltip"
        :class="{ izquierda: punto.aLaIzquierda }"
        :style="{ left: `${punto.x}px`, top: `${punto.y}px` }"
      >
        <strong>{{ titulo(punto.fila.est.nombre) }} · {{ fechaCorta(punto.fecha) }}</strong>
        <template v-if="punto.evento">
          <span>{{ mm(punto.evento.mm) }} en el día · {{ punto.evento.horas_lluvia }} h con lluvia</span>
          <span>Máximo en 1 h: {{ mm(punto.evento.max_hora_mm) }}</span>
        </template>
        <span v-else class="tenue">Sin lluvia sobre el mínimo</span>
        <span v-if="punto.pasada" class="g-tooltip-nisar">
          <i class="muestra-nisar" aria-hidden="true"></i>
          NISAR {{ fechaCorta(punto.pasada.hora_local) }} · pista {{ punto.pasada.pista }}
        </span>
      </div>
    </div>
  </figure>
</template>
