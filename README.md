# Detección de inundaciones urbanas en Lima Sur con Sentinel-1 y U-Net

Proyecto del curso de Machine Learning (Universidad ESAN). Segmentación de agua / inundación en imágenes SAR Sentinel-1 con U-Net, entrenada con Kuro Siwo (Chad, Harvey, Yibuti) y aplicada sin reentrenar a Lima (2017 y 2023).

El informe (LaTeX, IEEE) está en su propio repositorio: <https://github.com/23-Andres-QC/Informe-ProyectoMachineLearning>.

## Estructura

```
preparacion_datos.ipynb       1.º evalúa si cada fuente sirve para entrenar detección de agua y preprocesa
pipeline_inundaciones.ipynb   2.º entrenamiento y pruebas (dos modos: agua y cambio); solo lee datos preprocesados
predecir_tif.py               CLI: aplica un modelo entrenado a cualquier GeoTIFF VV/VH
src/
  config.py                   rutas, eventos, partición e hiperparámetros
  datos.py                    lectura de fuentes, corrección JRC, inventario, muestreo por evento, parches, normalización
  preparacion.py              calidad por evento, descarga JRC, pruebas (Bolivia, Lima) ya alineadas, vistas de cada fuente
  entrenamiento.py            Dataset, lotes balanceados, pérdida BCE+Dice, métricas, bucle de entrenamiento
  inferencia.py               ventana deslizante, HAND/JRC, Otsu, exportación GeoTIFF, resumen por distrito
scripts/
  descargar_s1_2023.py        descarga de escenas Sentinel-1 2023 (ASF)
  descargas_extra.py          Sen1Floods11 Bolivia + HAND, DEM y JRC
  grafo.xml                   grafo SNAP de preprocesamiento de las escenas de Lima
```

## Datos (no incluidos en el repositorio)

Colocar en `Data/` (o definir la variable de entorno `PML_DATOS`):

```
Data/
  kurosiwo/1111002 (Chad), 1111003 (Yibuti), 1111004 (Harvey)
  sen1floods11_bolivia/HandLabeled/{S1Hand,LabelHand}
  test_lima/procesadas/lima_2017_0305.tif, lima_2017_0317.tif, lima_2023_0304.tif, lima_2023_0316.tif
  test_lima/emsn038_2017/EMSN038_UTM18S_v0.gdb
  test_lima/auxiliares/{glo30_hand,glo30_dem,jrc_occurrence}
  test_lima/conida_2023/        mapas CONIDA (comparación visual en el informe)
  jrc_occurrence/               teselas JRC de los lugares de entrenamiento (las descarga preparacion_datos.ipynb)
```

Se descartaron, tras revisarlos a mano, Sen1Floods11 Colombia (etiquetas Otsu), UrbanSARFloods (polígonos gruesos, ríos sin etiquetar) y Kuro Siwo Madagascar (casi todo ríos y cuerpos grandes).

Las escenas de Lima se procesan en SNAP con `scripts/grafo.xml` (órbita, ruido térmico, calibración σ⁰, Refined Lee, corrección de terreno, dB, EPSG:32718 a 10 m).

## Uso

```bash
pip install -r requirements.txt
jupyter notebook preparacion_datos.ipynb      # 1.º: evalúa las fuentes y deja todo en Data/procesado/preparado/
jupyter notebook pipeline_inundaciones.ipynb  # 2.º: entrena y prueba leyendo solo Data/procesado/preparado/
```

`preparacion_datos.ipynb` muestra un ejemplo de cada dato y decide por evento si sirve para entrenar detección de agua (agua permanente etiquetada según JRC, agua visible en VH, tamaño de las manchas, separación por ΔVH); deja el porqué en `preparado/calidad.csv`. La validación son bloques geográficos de 10 km de Harvey.

Prueba rápida de todo el flujo (pocos parches, una época):

```bash
PML_RAPIDO=1 PML_SALIDA=/tmp/prueba jupyter nbconvert --to notebook --execute preparacion_datos.ipynb
PML_RAPIDO=1 PML_SALIDA=/tmp/prueba jupyter nbconvert --to notebook --execute pipeline_inundaciones.ipynb
```

Aplicar un modelo ya entrenado:

```bash
python predecir_tif.py Data/test_lima/procesadas/lima_2023_0316.tif --modo cambio \
    --pre Data/test_lima/procesadas/lima_2023_0304.tif --hand
```

Las salidas quedan en `Data/procesado/`: `preparado/` (parches, normalización, calidad, pruebas) y `resultados/` (modelos, métricas, GeoTIFF, mapa web).

## Alcance

El modelo detecta **dónde había agua en superficie cuando pasó el satélite**. No predice lluvia ni pronostica inundaciones.
