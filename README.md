# Detección de agua de lluvia (inundaciones y agua empozada) en ciudades del Perú con radar NISAR: U-Net y machine learning por píxel

Proyecto del curso de Machine Learning (Universidad ESAN). Segmentación de agua en imágenes de radar **NISAR** (NASA-ISRO,
banda L, 5 m) tomadas el día de una lluvia o en las horas siguientes, cuando el agua puede seguir empozada, en **Lima
(Lima Metropolitana y Callao), Tumbes y Arequipa**, con deep learning (U-Net) y con machine learning clásico por píxel. Cada lluvia se compara con días
secos de la misma pista y se valida con los lugares inundados que reportó la prensa.

El informe (LaTeX, IEEE) está en su propio repositorio: <https://github.com/23-Andres-QC/Informe-ProyectoMachineLearning>.

## Estructura

```
descarga_datos.ipynb                     1.º busca las imágenes NISAR RSLC (.h5) de cada lluvia y de días secos de la misma
                                             pista, revisa la lluvia antes de cada pasada (Open-Meteo) y baja solo el recorte
                                             de cada ciudad
01_segmentacion_deep_learning.ipynb      2.º geocodificación, máscara de agua, U-Net (ResNet34, EfficientNet-B0,
                                             MobileNetV2) y aplicación a Tumbes y Arequipa
02_segmentacion_machine_learning.ipynb   3.º clasificación por píxel (regresión logística, Random Forest, Gradient
                                             Boosting) y comparación con la U-Net
```

01 sigue la estructura datos → **preprocesamiento** (geocodificación de la RSLC a una grilla UTM de 5 m con el DEM,
HH en dB, máscara de agua del mismo día y validación de que cada escena sirve) → **normalización** → **modelo** →
**resultados** en validación → **aplicación externa** (Tumbes y Arequipa; agua de lluvia frente a días secos, validación
con los lugares de las noticias y coherencia en Lima Sur) → conclusiones. 02 usa las imágenes, máscaras y la validación
que deja el 01, y construye su propia tabla de píxeles.

| Rol | Escenas |
|---|---|
| train | Lima, pista 083 (18:25): 14 ene (solo Lima Sur y Centro), 18 ago y 5 oct 2026 |
| validación | Lima, pista 003 (05:58): 24 oct 2026 |
| aplicación externa | Tumbes, pista 003 (06:01): 24 oct 2026 · Arequipa, pista 046 (05:32): 17 feb 2026 (no pasa la validación de datos; solo entra en la comparación con días secos) · Lima 5 nov 2026 cuando se publique |
| referencia seca | Lima 083: 7 fechas · Lima 003: 5 fechas · Tumbes: 20 jul y 13 ago 2026 · Arequipa: 29 jun y 11 jul 2026 |

Los días secos no se usan para entrenar: sirven para separar el agua de la lluvia de lo que ya parece agua cualquier día
(mar, ríos, lagunas, langostineras, arena). Cada lluvia se compara con los días secos de su misma ciudad y pista.

Cada escena de lluvia entra a los modelos solo si pasa la validación de datos (contraste con el agua permanente de ESA
WorldCover 2021).

## Datos (no incluidos en el repositorio)

`descarga_datos.ipynb` baja NISAR del archivo de la NASA en ASF (cuenta gratuita de NASA Earthdata en `~/.netrc`):

```
Data/crudos_nisar/<ciudad>/*.h5         NISAR RSLC nivel 1, solo el recorte de la ciudad: números complejos HH
                                        originales en geometría de radar, grilla de geolocalización e identificación
                                        del producto (0.1-0.6 GB cada uno, ~13 GB en total; el archivo completo
                                        trae una franja de ~250 km y pesa 4-28 GB)
```

01 y 02 escriben en `Data/procesado/`:

```
nisar/<ciudad>/          DEM (altura sobre el elipsoide), ESA WorldCover y HH en dB (GeoTIFF UTM 5 m) por fecha; valor
                         complejo de Lima Sur (.npy) para la coherencia
etiquetas/               máscara de agua del mismo día (umbral de Kittler-Illingworth en terreno plano): 1 agua, 0 no
                         agua, 255 sin dato
validacion_datos.csv     ¿sirve cada escena? (contraste con ESA WorldCover 2021)
dl/                      U-Net: modelos (.pt), métricas (también por zona), historial, predicciones (GeoTIFF,
                         probabilidad × 100), agua de lluvia frente a días secos, validación con noticias y coherencia
ml/                      ML por píxel: modelos (.joblib), comparación con la U-Net (también por zona) y predicciones
```

El DEM Copernicus GLO-30 y ESA WorldCover se leen en línea de Microsoft Planetary Computer (sin cuenta).

## Requisitos

* Python con `pip install -r requirements.txt` (GPU CUDA recomendada; 16 GB de RAM).
* Cuenta gratuita de [NASA Earthdata](https://urs.earthdata.nasa.gov) guardada en `~/.netrc`.
* Unos 15 GB libres para los recortes y los productos procesados.

## Uso

```bash
jupyter notebook descarga_datos.ipynb                    # 1.º: recortes NISAR (~13 GB)
jupyter notebook 01_segmentacion_deep_learning.ipynb     # 2.º: geocodificación (~30 s por imagen) + U-Net (~50 min)
jupyter notebook 02_segmentacion_machine_learning.ipynb  # 3.º: ML por píxel y comparación con la U-Net
```

## Alcance

Qué se logró y qué no, con los números de la última ejecución (el detalle está en las conclusiones de cada notebook):

* **Agua abierta: sí.** La U-Net (ResNet34) logra IoU 0.75 en validación (Lima 24 oct) y 0.81 en Tumbes, una ciudad que
  no vio en el entrenamiento. Random Forest por píxel llega a 0.79 en los mismos píxeles de validación. Casi todo ese
  acierto está en el agua permanente (mar, ríos, langostineras: IoU 0.81-0.93).
* **Agua de lluvia en la ciudad: no.** Lejos del agua permanente el IoU baja a 0.02 en Lima y 0.32 en Tumbes. Lo que la
  etiqueta marca como agua en tierra ya está oscuro en los días secos en un 80-98 %: es arena, suelo y pozas, no lluvia. El
  agua de lluvia que queda al comparar con los días secos no se distingue de lo que el mismo criterio marca sin lluvia.
* **Noticias y coherencia.** En los lugares inundados según la prensa no aparece agua. En Tumbes y Arequipa toda la ciudad
  se oscurece 1-2 dB, y en Lima Sur la lluvia del 16-17 ago baja la coherencia de toda la zona (índice de tríada 0.25,
  contra 0.07 en un día seco): el radar ve la ciudad mojada, no los charcos.
* **Límites.** Una sola polarización (HH); pasadas entre 13 h y 3 días después de la lluvia; en Lima los días de lluvia y
  los secos tienen casi la misma garúa (0-6 mm en los 3 días previos); Arequipa no tiene agua permanente para validar la
  etiqueta; la etiqueta sale del mismo radar, no de campo.
* **Pendiente.** La pasada de Lima del 5 nov 2026 (horas después de los aniegos en Lima Sur) aún no está publicada en ASF.
  Cuando salga, `descarga_datos.ipynb` la baja y basta volver a ejecutar 01 y 02.
