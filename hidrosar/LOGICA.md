# HidroSAR · lógica del sistema

Detecta el agua de lluvia empozada en un área elegida en el mapa, usando imágenes de radar NISAR y el modelo entrenado.

## Piezas (Docker Compose, proyecto `hidrosar`)

| Contenedor | Qué hace |
|---|---|
| **web** (Vue + nginx) | Pantallas, mapa, dibujo del área. Pasa `/api` al backend. Es el único puerto expuesto. |
| **backend** (Go) | Login, usuarios, roles, lista de lluvias, búsqueda en NISAR, cola de evaluaciones, entrega de resultados. |
| **modelo** (Python) | Descarga solo el recorte del área, corre el modelo elegido y devuelve los polígonos de agua. |
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
   - Arriba del panel se elige el **modelo** (ver *Modelos*). La elección se recuerda en el navegador y se guarda con cada evaluación.
2. **Elegir el área.** Se dibuja un rectángulo en el mapa. Debe medir al menos 1 km por lado y como máximo 150 km².
3. **Elegir la fecha** de la lluvia.
4. **Buscar en NISAR.** El backend consulta el catálogo de la ASF para esa área y esa fecha.
   - **Si hay pasada**: "Se encontró el radar NISAR el dd/mm/aaaa a las HH:MM". Se muestran la cobertura del área (%) y la lluvia de las 24 h y 72 h previas.
   - **Si no hay**: "No se encontró el radar NISAR en esa fecha". Se muestran la pasada anterior y la siguiente.
   - Se elige automáticamente **un día seco de referencia**: la pasada más reciente antes de la lluvia, de la misma órbita y con menos de 1 mm de lluvia en 72 h (dato de Open-Meteo). Con uno basta y se descarga un recorte menos.
5. **Confirmar.** La evaluación entra a la cola y la pantalla muestra su estado: en cola → procesando → completado o error.
   - Si termina con error (por ejemplo, faltaba el modelo), **Reintentar** la vuelve a poner en cola sin buscar de nuevo.
6. **Procesar** (contenedor modelo, de una en una). El panel muestra cada paso con su estado (hecho, en curso, pendiente o con error), los MB que van descargados y los segundos de cada uno. El modelo lo informa en `GET /progreso/{id}`; el backend lo copia cada 2 s a la columna `progreso` y queda guardado, así se ve en qué paso falló una evaluación. Los pasos son:
   1. carga del modelo;
   2. relieve (DEM) y cobertura del suelo;
   3. descarga del recorte de la pasada de lluvia;
   4. descarga del día seco;
   5. segmentación;
   6. polígonos del agua y de los charcos.
   - Arma una grilla de 5 m sobre el área, con su relieve (DEM) y su cobertura del suelo (WorldCover).
   - Lee de NISAR **solo los bytes del recorte** y nunca la franja completa.
   - Si el área queda en parte fuera de la franja que tomó el radar, se segmenta solo la parte con datos. El panel avisa qué porcentaje se evaluó cuando es menos del 90 %.
   - Solo termina con error si la pasada no tiene datos en el área (menos del 1 %).
   - El día seco sirve de referencia si tiene datos en al menos el 20 % de lo que cubre la pasada de lluvia. Las evaluaciones viejas que guardaron dos días secos bajan solo el primero; el segundo se baja únicamente si el primero no tiene datos en el área.
   - Con un **modelo de agua**, que son las U-Net de 1 canal (Vol1 y Vol2) y el Machine Learning por píxel (Vol2) del notebook 01:
     - el modelo marca el agua el día de la lluvia;
     - se quita lo que también es agua en el día seco o en el mar, y lo que no se oscureció al menos 3 dB;
     - se quitan las manchas chicas y las que tocan ríos o lagunas.
   - Con un **modelo de cambio**, del pipeline final:
     - la imagen de la lluvia y la del día seco, con el nivel alineado al del día seco, entran juntas a la U-Net de 2 canales;
     - se queda lo que supera el umbral (0.9) en terreno plano (pendiente < 5°), sin agua permanente ni zonas que ya son oscuras en seco (< −18 dB);
     - como en la regla del pipeline, se quitan las manchas de menos de 10 píxeles (250 m²).
     - Sin día seco de referencia no se puede usar: el panel lo avisa antes de enviar.
   - El resultado se convierte en polígonos simplificados y recortados al rectángulo.
   - Con un modelo de agua se guarda además **toda el agua segmentada** ese día (mar, ríos, lagunas y charcos), sin las manchas de menos de 10 píxeles (250 m²). Es la capa azul de la sección 10.1 del notebook 01. Los modelos de cambio no la tienen, porque marcan solo el agua nueva.
7. **Ver el resultado.** El panel muestra las cifras y la lista de charcos de mayor a menor. Se pueden descargar en **KML** (Google Maps / Earth) o **GeoJSON**, con los charcos y el agua segmentada.
   - En el mapa, el agua segmentada va en **azul** y los charcos (agua de lluvia empozada) en **rosado** encima, como en el notebook 01.
   - El agua segmentada se pide aparte (`/api/evaluaciones/{id}/agua`) y solo cuando se dibuja la evaluación, porque con mar o ríos pesa más que los charcos.
   - La zona **no se dibuja sola** en el mapa al terminar. Se dibuja cuando se pide: **Ver en el mapa** en el panel, elegir un charco de la lista, o **Ver en el mapa** en la pestaña *Evaluaciones*.
   - Al elegir un charco, el mapa se acerca y lo resalta.
8. **Limpiar y evaluar otra zona.** Despeja el panel y el mapa: el área, la búsqueda, el pin y lo dibujado. La evaluación ya quedó guardada en *Evaluaciones*. Si aún se procesa, sigue en segundo plano.

## Modelos

Están en `hidrosar-modelo/modelos/` (ver su `LEEME.md`). El selector del panel los agrupa así:

| Grupo | Modelos | Entrada |
|---|---|---|
| Deep Learning · Vol1 | Ensamble y U-Net de cambio resnet34, efficientnet-b0, mobilenet_v2, vgg19_bn (carpeta `Vol1`, pipeline final) | Lluvia + día seco previo, a 5 m |
| Deep Learning · Vol2 | U-Net efficientnet-b0, mobilenet_v2, resnet34 y resnet34 desde cero, cada una con su umbral (carpeta `vol3/`, de ModelosVol3) | Imagen de radar a 5 m |
| Machine Learning · Vol2 | AdaBoost, árbol, HistGradientBoosting, KNN, MLP, Naive Bayes, Random Forest (y optimizado y + pendiente), regresión logística base, SVM rbf, XGBoost (carpeta `vol3/`) | Media y desviación de HH en 5×5 y 15×15 (y la pendiente en uno) a 5 m |

- El predeterminado es el de `MODELO_PT` en el `.env`.
- El servicio carga cada modelo cuando se pide y mantiene en memoria los 3 últimos.
- KNN y SVM son lentos en áreas grandes. El SVM tarda alrededor de un minuto en un recorte de 4 × 4 km.
- Los de Vol2 llevan «(Vol2)» en el nombre para no confundirlos en *Evaluaciones* con las U-Net de Vol1 que se llaman igual. Su id sigue siendo `vol3/…`, así las evaluaciones guardadas no pierden su modelo.
- El Machine Learning de Vol2 usa el umbral que trae cada archivo, elegido en validación en el notebook 01.
- Los modelos de agua superficial (Machine Learning a 20 m y U-Net de Keras) y las U-Net de 1 canal sueltas de la corrida anterior (`unet_<encoder>.pt`) se quitaron del selector. Las evaluaciones que se hicieron con ellos muestran el modelo como «(retirado)».

## Validaciones

La pestaña *Validaciones* lista el mejor modelo de cada grupo corrido en las zonas de validación de los notebooks. No muestra métricas: cada fila se abre en el mapa con **Ver en el mapa** (`?validacion=`).

| Grupo | Modelo que se valida | Por qué |
|---|---|---|
| Deep Learning · Vol1 | Ensamble de U-Net de cambio | «mejor modelo» de `pipeline-final.ipynb` |
| Deep Learning · Vol2 | U-Net efficientnet-b0 | mayor IoU en validación de las U-Net de `finalvol1.ipynb` |
| Machine Learning · Vol2 | Random Forest + pendiente | mayor IoU en validación de los modelos de ML de `finalvol1.ipynb` |

La lista está en `MODELOS` de `hidrosar-modelo/validacion.py`.

| Zona | Día | Día seco de la misma órbita |
|---|---|---|
| Iquitos (pista 155 D) | lluvia 04/09/2026 y 22/10/2026; seco 24/06/2026 | 24/06/2026 |
| Concepción (097 D) | lluvia 24/09/2026 | 19/08/2026 |
| Puerto Montt (104 A) | lluvia 15/07/2026 | — |
| Lima Sur (003 A) | lluvia 05/11/2026 | 25/08/2026 |

- En el mapa se ven tres capas, cada una se puede apagar:
  - **aciertos** (azul): agua que marcan el modelo y la referencia;
  - **falsas alarmas** (ámbar): agua que marca el modelo y la referencia no;
  - **omisiones** (rosa, borde punteado): agua de la referencia que el modelo no marca.
- La referencia de las U-Net y el Machine Learning de Vol2 es la etiqueta de `finalvol1.ipynb`: HH suavizado bajo el umbral calibrado con el agua permanente de WorldCover, en terreno plano, sin manchas de menos de 40 píxeles. En el día seco es el agua permanente de WorldCover.
- La referencia de las U-Net de cambio de Vol1 es la regla de `pipeline-final.ipynb`: HH 3 dB o más por debajo del día seco, en la zona evaluable. Solo se validan en las zonas con día seco de la misma órbita.
- Se usan los recortes que ya están en `Data/crudos_nisar` (montado en el servicio del modelo como `/crudos`, solo lectura): no se descarga nada de NISAR.
- Se calculan en segundo plano, una a la vez y siempre después de las evaluaciones de los usuarios. El backend agrega las que faltan cada 5 minutos (por ejemplo, si se copia un modelo nuevo). Solo se guardan los polígonos en PostGIS (tabla `validaciones`).
- El administrador puede **recalcular** una validación terminada.

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
