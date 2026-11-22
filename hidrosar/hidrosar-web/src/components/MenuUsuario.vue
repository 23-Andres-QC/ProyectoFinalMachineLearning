<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { sesion } from '../sesion'
import Icono from './Icono.vue'
import Preferencias from './Preferencias.vue'

// Menú de la cuenta: avatar con iniciales que despliega el tamaño de letra, cambiar contraseña y cerrar sesión.
// Es un botón que muestra/oculta un panel (patrón de divulgación): se cierra con Esc o al hacer clic fuera.
const emit = defineEmits(['clave', 'salir'])
const abierto = ref(false)
const raiz = ref(null)
const boton = ref(null)

const ROLES = { administrador: 'Administrador', evaluador: 'Evaluador' }
const iniciales = computed(() =>
  (sesion.usuario?.nombre || '?')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toLocaleUpperCase('es-PE'),
)

function alTocarFuera(e) {
  if (!raiz.value?.contains(e.target)) abierto.value = false
}

function alTeclear(e) {
  if (e.key !== 'Escape') return
  abierto.value = false
  boton.value?.focus()
}

function escuchar(si) {
  const metodo = si ? 'addEventListener' : 'removeEventListener'
  document[metodo]('pointerdown', alTocarFuera)
  document[metodo]('keydown', alTeclear)
}

watch(abierto, escuchar)
onBeforeUnmount(() => escuchar(false))

function elegir(accion) {
  abierto.value = false
  emit(accion)
}
</script>

<template>
  <div ref="raiz" class="menu-usuario">
    <button
      ref="boton"
      type="button"
      class="menu-usuario-boton"
      :aria-expanded="abierto"
      aria-controls="menu-usuario-panel"
      :aria-label="`Cuenta de ${sesion.usuario.nombre}`"
      @click="abierto = !abierto"
    >
      <span class="avatar" aria-hidden="true">{{ iniciales }}</span>
      <span class="menu-usuario-nombre">{{ sesion.usuario.nombre }}</span>
      <Icono nombre="abajo" :tam="16" class="menu-flecha" />
    </button>

    <Transition name="menu">
      <div v-if="abierto" id="menu-usuario-panel" class="menu-panel">
        <div class="menu-cabeza">
          <span class="avatar grande" aria-hidden="true">{{ iniciales }}</span>
          <div>
            <strong>{{ sesion.usuario.nombre }}</strong>
            <span class="tenue">{{ sesion.usuario.email }}</span>
          </div>
        </div>
        <span class="etiqueta menu-rol">{{ ROLES[sesion.usuario.rol] || sesion.usuario.rol }}</span>
        <div class="menu-separador" role="presentation"></div>
        <div class="menu-fila">
          <span class="menu-fila-texto"><Icono nombre="letra" /> Tamaño de letra</span>
          <Preferencias mostrar="letra" />
        </div>
        <button type="button" class="menu-item" @click="elegir('clave')">
          <Icono nombre="llave" /> Cambiar contraseña
        </button>
        <div class="menu-separador" role="presentation"></div>
        <button type="button" class="menu-item peligro" @click="elegir('salir')">
          <Icono nombre="salir" /> Cerrar sesión
        </button>
      </div>
    </Transition>
  </div>
</template>
