<script setup>
import { onMounted, reactive, ref } from 'vue'
import { api } from '../api'
import Confirmar from '../components/Confirmar.vue'
import { fechaHora } from '../formato'
import { cargarSesion, sesion } from '../sesion'

const usuarios = ref([])
const cargando = ref(true)
const error = ref('')
const dialogo = ref(null)
const confirmar = ref(null)
const formulario = reactive({ id: null, nombre: '', email: '', rol: 'evaluador', clave: '', activo: true })
const errorFormulario = ref('')
const guardando = ref(false)
const ROLES = { administrador: 'Administrador', evaluador: 'Evaluador' }

const esYo = (u) => u.id === sesion.usuario?.id

async function cargar() {
  try {
    usuarios.value = (await api('/usuarios')) || []
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    cargando.value = false
  }
}

function abrir(u = null) {
  Object.assign(
    formulario,
    u
      ? { id: u.id, nombre: u.nombre, email: u.email, rol: u.rol, clave: '', activo: u.activo }
      : { id: null, nombre: '', email: '', rol: 'evaluador', clave: '', activo: true },
  )
  errorFormulario.value = ''
  dialogo.value.showModal()
}

async function guardar() {
  guardando.value = true
  errorFormulario.value = ''
  const { id, ...datos } = formulario
  try {
    if (id) await api(`/usuarios/${id}`, { metodo: 'PUT', datos })
    else await api('/usuarios', { metodo: 'POST', datos })
    dialogo.value.close()
    if (id === sesion.usuario?.id) await cargarSesion()
    await cargar()
  } catch (e) {
    errorFormulario.value = e.message
  } finally {
    guardando.value = false
  }
}

async function cambiarActivo(u) {
  try {
    await api(`/usuarios/${u.id}`, { metodo: 'PUT', datos: { nombre: u.nombre, email: u.email, rol: u.rol, clave: '', activo: !u.activo } })
    await cargar()
  } catch (e) {
    error.value = e.message
  }
}

async function eliminar(u) {
  const ok = await confirmar.value.preguntar({
    titulo: `¿Eliminar a ${u.nombre}?`,
    texto: `Se borran también sus ${u.evaluaciones} evaluaciones. Si solo quieres quitarle el acceso, desactívalo.`,
    aceptar: 'Eliminar',
    peligro: true,
  })
  if (!ok) return
  try {
    await api(`/usuarios/${u.id}`, { metodo: 'DELETE' })
    await cargar()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(cargar)
</script>

<template>
  <div class="pagina">
    <div class="encabezado">
      <h1>Usuarios</h1>
      <button type="button" class="boton" @click="abrir()">Nuevo usuario</button>
    </div>
    <p class="ayuda">
      El <strong>administrador</strong> gestiona usuarios y ve todas las evaluaciones. El <strong>evaluador</strong> evalúa y ve
      solo las suyas.
    </p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="cargando" class="tenue">Cargando…</p>
    <div v-else class="tabla-contenedor">
      <table class="tabla">
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Correo</th>
            <th>Rol</th>
            <th>Estado</th>
            <th class="num">Evaluaciones</th>
            <th>Último acceso</th>
            <th><span class="oculto">Acciones</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in usuarios" :key="u.id">
            <td>{{ u.nombre }} <span v-if="esYo(u)" class="tenue">(tú)</span></td>
            <td>{{ u.email }}</td>
            <td><span class="etiqueta">{{ ROLES[u.rol] }}</span></td>
            <td><span class="estado" :class="u.activo ? 'completado' : 'error'">{{ u.activo ? 'Activo' : 'Inactivo' }}</span></td>
            <td class="num">{{ u.evaluaciones }}</td>
            <td>{{ fechaHora(u.ultimo_acceso) }}</td>
            <td class="acciones-fila">
              <button type="button" class="boton-texto" @click="abrir(u)">Editar</button>
              <template v-if="!esYo(u)">
                <button type="button" class="boton-texto" @click="cambiarActivo(u)">{{ u.activo ? 'Desactivar' : 'Activar' }}</button>
                <button type="button" class="boton-texto peligro" @click="eliminar(u)">Eliminar</button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <dialog ref="dialogo" class="dialogo" aria-labelledby="titulo-usuario">
      <h2 id="titulo-usuario">{{ formulario.id ? 'Editar usuario' : 'Nuevo usuario' }}</h2>
      <form class="formulario" @submit.prevent="guardar">
        <label>Nombre
          <input v-model.trim="formulario.nombre" type="text" autocomplete="off" required maxlength="100">
        </label>
        <label>Correo
          <input v-model.trim="formulario.email" type="email" autocomplete="off" required>
        </label>
        <label>Rol
          <select v-model="formulario.rol" :disabled="formulario.id === sesion.usuario?.id">
            <option value="evaluador">Evaluador</option>
            <option value="administrador">Administrador</option>
          </select>
        </label>
        <label>Contraseña
          <input
            v-model="formulario.clave"
            type="password"
            autocomplete="new-password"
            minlength="8"
            :required="!formulario.id"
            :placeholder="formulario.id ? 'Vacía para no cambiarla' : 'Mínimo 8 caracteres'"
          >
        </label>
        <label v-if="formulario.id && formulario.id !== sesion.usuario?.id" class="casilla">
          <input v-model="formulario.activo" type="checkbox"> Activo (puede ingresar)
        </label>
        <p v-if="errorFormulario" class="error" role="alert">{{ errorFormulario }}</p>
        <div class="acciones">
          <button type="button" class="boton secundario" @click="dialogo.close()">Cancelar</button>
          <button class="boton" :disabled="guardando">{{ guardando ? 'Guardando…' : 'Guardar' }}</button>
        </div>
      </form>
    </dialog>
    <Confirmar ref="confirmar" />
  </div>
</template>
