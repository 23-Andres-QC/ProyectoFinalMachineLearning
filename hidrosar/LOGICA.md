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

La pestaña tiene dos fuentes; se elige arriba y se recuerda en el navegador.

**Estaciones del Senamhi** (fuente por defecto)

- Lluvia **medida cada hora** por las estaciones automáticas del Senamhi en Lima. Vienen de las tablas CSV que exporta su portal, guardadas en las tablas `estaciones_senamhi` y `lluvia_senamhi`.
- Estaciones cargadas: Campo de Marte, San Juan de Lurigancho, Villa María del Triunfo y Ñaña, con datos de 2025 a hoy. También Pantanos de Villa y San Borja, que en las tablas no traen lluvia ("S/D").
- Por cada estación y día se muestran:
  - la suma del día;
  - las horas con lluvia;
  - el máximo en 1 hora;
  - cuántas de las 24 horas tienen dato.
- Se filtra por estación, rango de fechas (desde el 01/01/2024, máximo un año) y lluvia mínima.
- Sobre la tabla hay un **gráfico de lluvia diaria**: una franja por estación, con una barra por día y un triángulo naranja bajo la línea en cada pasada de NISAR. A la derecha van el total del periodo y el día más lluvioso. Al pasar el mouse se ve el detalle del día.
  - **Escala por estación** (por defecto): cada franja llega hasta su día más lluvioso, así se ve la garúa de todas las estaciones.
  - **Misma escala**: todas las franjas usan la misma escala, para comparar cantidades entre estaciones.
- El administrador puede **subir más tablas** (.csv, hasta 60 MB por envío). Las horas que ya existían se actualizan y no se duplican. Una carpeta completa también se carga desde la consola: `docker compose run --rm --no-deps -v "<carpeta>:/senamhi:ro" backend importar-senamhi /senamhi`.

**Ciudades (Open-Meteo)**

- Se filtra por **región** (o todo el Perú), **ciudad**, rango de fechas y lluvia mínima en mm.
- Cubre las capitales de región y las ciudades principales del Perú (71 puntos).
- La lluvia diaria viene de **Open-Meteo**, la misma fuente de la "lluvia previa". Es una estimación de modelos meteorológicos, no de pluviómetros.

**En las dos fuentes**

- Para cada día de lluvia se indica si **NISAR pasó** sobre la estación o la ciudad ese día o el siguiente. Eso sale del catálogo de ASF, contando solo las pasadas cuya huella cubre el punto.
- **Evaluar** abre el mapa con un área sugerida de unos 6.6 × 6.6 km alrededor del punto, la fecha de la pasada y la búsqueda en NISAR ya hecha.
- **Ir al lugar** abre el mapa acercado al punto, con un pin y la fecha del día de lluvia. No dibuja ningún área ni busca nada.
- Las consultas a ASF y Open-Meteo se guardan 1 hora en memoria para no repetirlas.

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
7. **Ver el resultado.** El panel muestra las cifras y la lista de charcos de mayor a menor. Se pueden descargar en **KML** (Google Maps / Earth) o **GeoJSON**.
   - La zona **no se dibuja sola** en el mapa al terminar. Se dibuja cuando se pide: **Ver en el mapa** en el panel, elegir un charco de la lista, o **Ver en el mapa** en la pestaña *Evaluaciones*.
   - Al elegir un charco, el mapa se acerca y lo resalta.
8. **Limpiar y evaluar otra zona.** Despeja el panel y el mapa: el área, la búsqueda, el pin y lo dibujado. La evaluación ya quedó guardada en *Evaluaciones*. Si aún se procesa, sigue en segundo plano.

## Historial en el mapa

- El historial está en la pestaña *Evaluaciones*; el panel del mapa solo tiene los pasos para evaluar.
- Al abrir el mapa **no se dibuja nada** del historial. Solo se dibuja lo que se pide desde *Evaluaciones*:
  - **Ver en el mapa** en una fila (abre el mapa con `?id=` y dibuja esa);
  - **Ver todas en el mapa** en el encabezado (abre el mapa con `?todas=` y dibuja todas).
- **Limpiar mapa** (en el paso 1) quita del mapa todo lo dibujado.
- El evaluador ve lo suyo y el administrador ve todo.
- **Con el mapa lejos** (todo el Perú), cada evaluación es un marcador:
  - rojo con el número de charcos;
  - celeste si no hubo agua o si sigue en proceso;
  - naranja con "!" si terminó con error.
- **Al acercar**, se ven el contorno de cada área evaluada y un punto rojo sobre cada charco, para que los charcos chicos no se pierdan.
- **Muy cerca**, quedan solo los polígonos reales del agua.
- Clic en un área: abre su evaluación. Clic en un charco: abre su evaluación y acerca a ese charco.
- Mientras alguna evaluación está en proceso, el panel y lo que esté dibujado se actualizan solos.
- Una evaluación recién enviada se sigue en el panel con `?seguir=` (sin dibujarla); recargar la página no la pierde.

## Preferencias de la interfaz

- El botón de luna / sol de la barra cambia entre tema claro y oscuro. Sin elegir, sigue el del sistema.
- El botón con las iniciales del usuario abre el menú de la cuenta: nombre, correo y rol; **Tamaño de letra** (A− / A+, de 87.5 % a 137.5 %, en toda la app, mapa incluido); **Cambiar contraseña** y **Cerrar sesión**. Se cierra con Esc o con un clic afuera.
- Las dos se recuerdan en el navegador y se aplican antes de pintar la página, para que no parpadee.
- En el login, el ojo del campo de contraseña la muestra u oculta (se vuelve a ocultar al enviar, para que el navegador pueda guardarla) y aparece un aviso si Bloq Mayús está activado.
- El fondo del login es un video en 1920 × 1080, a media velocidad y en bucle. En tema claro es la Tierra y en oscuro, lluvia sobre los árboles. Con "reducir movimiento" activado en el sistema, queda una foto fija.
- En pantallas angostas las tablas se desplazan de lado dentro de su marco; la página nunca se desborda. Por debajo de 1100 px el nombre del usuario sale de la barra (sigue en el menú de la cuenta) y las acciones de la tabla pueden pasar a dos líneas; por debajo de 520 px la navegación muestra solo íconos, salvo la sección activa.
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
