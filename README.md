# Detección de agua de lluvia (inundaciones y agua empozada) en ciudades grandes con radar (Sentinel-1 y NISAR): U-Net y machine learning por píxel (Lima)

Proyecto del curso de Machine Learning (Universidad ESAN). Segmentación de agua en imágenes de radar Sentinel-1 tomadas el día
de una lluvia o en los días siguientes, cuando el agua puede seguir empozada, en ciudades grandes y áridas (Lima, Dubái, Karachi, El Cairo, Mascate), con deep learning (U-Net) y con
machine learning clásico por píxel, y aplicación a las lluvias de Lima de 2026. Los aniegos de Lima Sur se revisan también
con radar NISAR de 5 m.

El informe (LaTeX, IEEE) está en su propio repositorio: <https://github.com/23-Andres-QC/Informe-ProyectoMachineLearning>.

## Estructura

```
descarga_datos.ipynb                     1.º baja las escenas Sentinel-1 originales (.SAFE) de cada lluvia y de días secos,
                                             y las imágenes NISAR (RSLC) de Lima Sur
01_segmentacion_deep_learning.ipynb      2.º U-Net (ResNet34, EfficientNet-B0, MobileNetV2)
02_segmentacion_machine_learning.ipynb   3.º clasificación por píxel (regresión logística, Random Forest, Gradient
                                             Boosting) y comparación con la U-Net
```

01 sigue la estructura datos → **preprocesamiento** (SNAP, dB, máscara de agua del mismo día y validación de que cada
escena sirve) → **normalización** → **modelo** → **resultados** en validación → **aplicación externa** (Lima 2026, con
comparación contra días secos y validación con los aniegos reportados en la prensa y con el desborde del Huaycoloro y
del Rímac de 2017; persistencia del agua empozada entre pasadas; NISAR de 5 m: amplitud y coherencia) → conclusiones. 02 usa las escenas,
máscaras y la validación que deja el 01, y construye su propia tabla de píxeles.

| Rol | Escenas de Lima |
|---|---|
| train | 17 mar 2017, 23 ene 2018, 19 mar 2019, 10, 11 y 16 ene 2026 (días de lluvia) |
| validación | 16 mar 2023 (ciclón Yaku), 4 ene 2025 (días de lluvia) |
| aplicación externa | 17 ago, 3 oct, 22 oct, 3 nov, 8 nov y 9 nov 2026 (días de lluvia) |
| referencia seca 2026 | 18 mar, 17 abr, 29 abr, 23 may y 17 jul 2026 (mañana); 18 abr, 30 abr, 6 may, 12 jul y 28 sep 2026 (tarde) |
| referencia seca 2017 | 12 sep 2016; 16 may, 9 jun, 3 jul y 20 ago 2017 (mañana), para las lluvias de 2017-2019 |

Los días secos no se usan para entrenar: sirven para separar el agua de la lluvia de lo que ya parece agua cualquier día
(pistas, arena, orilla del mar). Cada lluvia se compara con los días secos de su mismo pase y de su época.

Cada escena entra a los modelos solo si pasa la validación de datos (contraste con el agua permanente de ESA WorldCover 2021).
Dubái, El Cairo, Karachi y Mascate se descargaron pero no pasan: la arena del desierto sale tan oscura como el agua y el mar
con viento no sale oscuro en VV.

## Datos (no incluidos en el repositorio)

`descarga_datos.ipynb` baja Sentinel-1 de Microsoft Planetary Computer (sin cuenta) y NISAR del archivo de la NASA en ASF
(cuenta gratuita de NASA Earthdata en `~/.netrc`):

```
Data/crudos/<ciudad>/<escena>.SAFE/     producto Sentinel-1 GRD original del día de lluvia
    measurement/*.tiff                  VV y VH (números digitales, geometría de radar)
    annotation/**/*.xml                 anotación, calibración y ruido térmico
    manifest.safe
Data/referencia_seca/lima/<escena>.SAFE/  igual, de días sin lluvia (solo referencia)
Data/crudos_nisar/lima/*.h5             NISAR RSLC nivel 1 (complejo, geometría de radar), pistas 083 y 003
```

01 y 02 escriben en `Data/procesado/`:

```
escenas/                 σ⁰ VH, σ⁰ VV y máscara de sombra de radar por escena (GeoTIFF UTM 10 m, salida de SNAP)
referencia/              lo mismo para los días secos
etiquetas/               máscara de agua del mismo día (Otsu + pendiente): 1 agua, 0 no agua, 255 sin dato
validacion_datos.csv     ¿sirve cada escena? (contraste con ESA WorldCover 2021)
dl/                      U-Net: modelos (.pt), métricas, historial, predicciones (GeoTIFF, probabilidad × 100),
                         agua de lluvia frente a días secos y validación con noticias
ml/                      ML por píxel: modelos (.joblib), comparación con la U-Net y predicciones
nisar/                   NISAR en UTM 5 m de Lima Sur: HH (dB), valor complejo (.npy), DEM y validación con noticias
```

La pendiente (DEM Copernicus GLO-30) y ESA WorldCover se leen en línea de Planetary Computer; no se guardan.

## Requisitos

* Python con `pip install -r requirements.txt` (GPU CUDA recomendada; 16 GB de RAM).
* Para NISAR, cuenta gratuita de [NASA Earthdata](https://urs.earthdata.nasa.gov) guardada en `~/.netrc`.
* [SNAP](https://step.esa.int/main/download/snap-download/) instalado en `~/esa-snap` (se usa `gpt`). La primera vez descarga
  órbitas y el DEM Copernicus de 30 m.

## Uso

```bash
jupyter notebook descarga_datos.ipynb                    # 1.º: Sentinel-1 (~38 GB, 20-60 min) y NISAR (~72 GB, horas)
jupyter notebook 01_segmentacion_deep_learning.ipynb     # 2.º: SNAP (~2-5 min por escena la primera vez) + U-Net
jupyter notebook 02_segmentacion_machine_learning.ipynb  # 3.º: ML por píxel y comparación con la U-Net
```

## Alcance

Los modelos detectan **agua abierta en superficie cuando pasó el satélite** (mar, lagunas grandes y quietas). La máscara de
entrenamiento sale de un umbral sobre la misma imagen (el día de la lluvia no hay imagen óptica sin nubes), así que las
métricas miden el parecido con esa máscara, no con inundaciones reales.

**Sí detecta un desborde de río que cubre cuadras enteras** (notebook 01, sección 6.3). El 17 mar 2017, con el Huaycoloro y
el Rímac desbordados en Huachipa, Campoy y Carapongo, el radar VV sube 0.5-1.2 dB en los 4 lugares reportados por la prensa
frente a los días secos de 2016-2017, más que en el 97-99 % de las zonas urbanas de Lima del mismo tamaño. La U-Net no lo
marca como agua: el barro y el agua entre casas *suben* el radar en vez de bajarlo, así que la señal está en el cambio
contra días secos, no en la segmentación.

**No detecta los aniegos urbanos.** En los 9 casos de 2026 reportados por la prensa (baipás Nueva Esperanza, VES Sector 1
Grupo 1, José Gálvez, Av. Los Héroes, Hospital de Emergencias de VES) la U-Net no marca agua. El radar sube un poco en esos
lugares (el agua junto a las paredes hace doble rebote), pero ese día entre 2.5 y 27 de cada 100 zonas urbanas de Lima del
mismo tamaño cambian igual o más. Con NISAR de 5 m (secciones 6.5-6.6) tampoco: la amplitud del baipás el 18 ago cae dentro
de lo que varía un día seco, y la coherencia muestra que la lluvia cambió toda la ciudad, no los lugares de las noticias.
Los aniegos son más angostos que la resolución real de Sentinel-1 (~20 m) y NISAR (~5-10 m), y muchas veces el agua ya se
había ido cuando pasó el satélite; para verlos harían falta imágenes de ~1-3 m a la hora del aniego (ICEYE, Capella,
PerúSAT-1 o Planet sin nubes) o datos de campo. No predice lluvia ni pronostica inundaciones.

**Agua empozada: señal en el sentido esperado, pero no separable** (notebook 01, sección 6.4). El agua que se queda horas
o días en baipases y calles debería verse en dos pasadas seguidas. Del 8 al 9 nov 2026 siguen 0.021 km² de agua de lluvia
(pares de días secos: 0-0.008 km²), pero en la orilla del mar de Lurín y en dos terrenos de arena de Chorrillos y VES
(posibles charcos sin confirmar), no en las calles con noticias. Tres días después de los aniegos del 4-5 nov, el baipás
Nueva Esperanza, VES Sector 1 y el Hospital de VES suben más que todos los días secos, pero ese día también lo hace el
28 % de Lima Sur, mojada por la llovizna.
