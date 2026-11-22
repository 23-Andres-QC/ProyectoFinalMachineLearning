# HidroSAR · lógica del sistema

Detecta el agua de lluvia empozada en un área elegida en el mapa, usando imágenes de radar NISAR y el modelo entrenado.

## Piezas (Docker Compose, proyecto `hidrosar`)

| Contenedor | Qué hace |
|---|---|
| **web** (Vue + nginx) | Pantallas, mapa, dibujo del área. Pasa `/api` al backend. Es el único puerto expuesto. |
| **backend** (Go) | Login, usuarios, roles, lista de lluvias, búsqueda en NISAR, cola de evaluaciones, entrega de resultados. |
| **modelo** (Python) | Descarga solo el recorte del área, corre la U-Net y devuelve los polígonos de agua. |
| **db** (PostgreSQL + PostGIS) | Usuarios, evaluaciones y polígonos resultantes. |

## Usuarios y roles

- **Administrador**: crea, edita, desactiva y elimina usuarios. Ve todas las evaluaciones.
- **Evaluador**: solo evalúa y ve sus propias evaluaciones.
- El primer administrador se crea al arrancar, con los datos del `.env`.
- La sesión dura 12 horas y viaja en una cookie que el navegador no puede leer.
- Si un usuario se desactiva, pierde el acceso en su siguiente petición.
- El login bloquea por 5 minutos después de 10 intentos fallidos.

## Lista de lluvias (pestaña *Lluvias*)

- Se filtra por **región** (o todo el Perú), **ciudad**, rango de fechas y lluvia mínima en mm.
- Cubre las capitales de región y las ciudades principales del Perú (71 puntos).
- La lluvia diaria viene de **Open-Meteo**, la misma fuente de la "lluvia previa". Es una estimación de modelos meteorológicos, no de pluviómetros.
- Para cada día de lluvia se indica si **NISAR pasó** sobre la ciudad ese día o el siguiente. Eso sale del catálogo de ASF, contando solo las pasadas cuya huella cubre la ciudad.
- **Evaluar** abre el mapa con un área sugerida de unos 6.6 × 6.6 km alrededor de la ciudad, la fecha de la pasada y la búsqueda en NISAR ya hecha.
- Las consultas se guardan 1 hora en memoria para no repetirlas.

## Flujo de una evaluación

1. **Login.** Se entra al mapa, o se elige una lluvia de la lista.
2. **Elegir el área.** Se dibuja un rectángulo en el mapa. Debe medir al menos 1 km por lado y como máximo 150 km².
3. **Elegir la fecha** de la lluvia.
4. **Buscar en NISAR.** El backend consulta el catálogo de la ASF para esa área y esa fecha.
   - **Si hay pasada**: "Se encontró el radar NISAR el dd/mm/aaaa a las HH:MM". Se muestran la cobertura del área (%) y la lluvia de las 24 h y 72 h previas.
   - **Si no hay**: "No se encontró el radar NISAR en esa fecha". Se muestran la pasada anterior y la siguiente.
   - Se eligen automáticamente hasta 2 **días secos de referencia**, de la misma órbita y con menos de 1 mm de lluvia en 72 h (dato de Open-Meteo).
5. **Confirmar.** La evaluación entra a la cola y la pantalla muestra su estado: en cola → procesando → completado o error.
   - Si termina con error (por ejemplo, faltaba el modelo), **Reintentar** la vuelve a poner en cola sin buscar de nuevo.
6. **Procesar** (contenedor modelo, de una en una):
   - Arma una grilla de 5 m sobre el área, con su relieve (DEM) y su cobertura del suelo (WorldCover).
   - Lee de NISAR **solo los bytes del recorte** y nunca la franja completa.
   - Si la pasada cubre menos del 20 % del área, termina con error.
   - La U-Net marca el agua el día de la lluvia.
   - Se quita lo que también es agua en los días secos o en el mar, y lo que no se oscureció al menos 3 dB.
   - Se quitan las manchas chicas y las que tocan ríos o lagunas.
   - El resultado se convierte en polígonos simplificados y recortados al rectángulo.
7. **Ver el resultado.** En el mismo mapa aparecen los charcos en rojo, con su número y su área. Se pueden descargar en **KML** (Google Maps / Earth) o **GeoJSON**.
   - Al terminar, el mapa se acerca solo a los charcos.
   - El panel lista los charcos de mayor a menor. Al elegir uno, el mapa se acerca y lo resalta.

## Historial en el mapa

- Al abrir el mapa se dibuja **todo lo procesado**. El evaluador ve lo suyo y el administrador ve todo.
- **Con el mapa lejos** (todo el Perú), cada evaluación es un marcador:
  - rojo con el número de charcos;
  - celeste si no hubo agua o si sigue en proceso;
  - naranja con "!" si terminó con error.
- **Al acercar**, se ven el contorno de cada área evaluada y un punto rojo sobre cada charco, para que los charcos chicos no se pierdan.
- **Muy cerca**, quedan solo los polígonos reales del agua.
- Clic en un área: abre su evaluación. Clic en un charco: abre su evaluación y acerca a ese charco.
- El panel muestra el resumen del historial (evaluaciones, charcos, m² de agua) y las 8 más recientes.
- Mientras alguna evaluación está en proceso, el mapa se actualiza solo.
- El historial vive en la base de datos. Sobrevive a reinicios y solo se borra al eliminar la evaluación o el volumen. Cómo respaldarlo: ver el README.

## Qué se guarda (lo mínimo)

- Por evaluación: el rectángulo, la fecha, los datos de la pasada, el estado y los totales (charcos, m² de agua, MB descargados).
- El resultado es **un solo multipolígono**, con coordenadas redondeadas a ~10 cm y simplificado a 2.5 m. Pesa unos pocos KB.
- **No se guardan** imágenes, rásteres ni archivos de NISAR: todo vive en memoria mientras se procesa y luego se descarta.

## Reglas de seguridad

- El navegador nunca envía URLs de descarga. El backend recuerda la búsqueda por 1 hora y la evaluación se pide por su número.
- El modelo solo acepta archivos `.h5` del servidor de NISAR en la ASF.
- Las contraseñas se guardan con bcrypt.
- Las credenciales de NASA Earthdata y los secretos solo están en el `.env`, que no se sube a git.
- El modelo entrenado (`.pt`) se copia a `hidrosar-modelo/modelos/` y tampoco se sube.

## Errores que ve el usuario

- Área demasiado chica o demasiado grande.
- Búsqueda vencida: hay que volver a buscar.
- Falta el modelo `.pt` o faltan las credenciales de Earthdata.
- NASA rechazó las credenciales.
- La pasada no cubre lo suficiente del área.
