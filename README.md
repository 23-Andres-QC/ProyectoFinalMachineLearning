# Detección de inundaciones urbanas en Lima Sur con Sentinel-1 y U-Net

Proyecto del curso de Machine Learning (Universidad ESAN). Segmentación de agua / inundación en imágenes SAR Sentinel-1 con U-Net, entrenada con datasets internacionales (Sen1Floods11, Kuro Siwo, UrbanSARFloods) y aplicada sin reentrenar a Lima (2017 y 2023).

El informe (LaTeX, IEEE) está en su propio repositorio: <https://github.com/23-Andres-QC/Informe-ProyectoMachineLearning>.

## Estructura

```
pipeline_inundaciones.ipynb   pipeline completo (datasets completos, dos modos: agua y cambio)
entrenamiento_muestra.ipynb   versión anterior sobre la muestra (referencia)
predecir_tif.py               CLI: aplica un modelo entrenado a cualquier GeoTIFF VV/VH
src/
  config.py                   rutas, eventos, partición e hiperparámetros
  datos.py                    lectura de fuentes, inventario, muestreo por evento, parches, normalización
  entrenamiento.py            Dataset, lotes balanceados, pérdida BCE+Dice, métricas, bucle de entrenamiento
  inferencia.py               ventana deslizante, HAND/JRC, Otsu, exportación GeoTIFF, resumen por distrito
scripts/
  descargar_s1_2023.py        descarga de escenas Sentinel-1 2023 (ASF)
  descargas_extra.py          Sen1Floods11 Bolivia + HAND, DEM y JRC
  grafo.xml                   grafo SNAP de preprocesamiento de las escenas de Lima
  crear_muestra.py            generación de la muestra pequeña usada al inicio
```

## Datos (no incluidos en el repositorio)

Colocar en `Data/` (o definir la variable de entorno `PML_DATOS`):

```
Data/
  sen1floods11_colombia/WeaklyLabeled/{S1Weak,S1OtsuLabelWeak}
  sen1floods11_bolivia/HandLabeled/{S1Hand,LabelHand}
  kurosiwo/1111002 … 1111006
  urbansarfloods/urban_sar_floods/{01_NF,02_FO,03_FU}/{SAR,GT}
  test_lima/procesadas/lima_2017_0305.tif, lima_2017_0317.tif, lima_2023_0304.tif, lima_2023_0316.tif
  test_lima/emsn038_2017/EMSN038_UTM18S_v0.gdb
  test_lima/auxiliares/{glo30_hand,glo30_dem,jrc_occurrence}
```

Las escenas de Lima se procesan en SNAP con `scripts/grafo.xml` (órbita, ruido térmico, calibración σ⁰, Refined Lee, corrección de terreno, dB, EPSG:32718 a 10 m).

## Uso

```bash
pip install -r requirements.txt
jupyter notebook pipeline_inundaciones.ipynb
```

Prueba rápida de todo el flujo (pocos parches, una época):

```bash
PML_RAPIDO=1 PML_SALIDA=/tmp/prueba jupyter nbconvert --to notebook --execute pipeline_inundaciones.ipynb
```

Aplicar un modelo ya entrenado:

```bash
python predecir_tif.py Data/test_lima/procesadas/lima_2023_0316.tif --modo cambio \
    --pre Data/test_lima/procesadas/lima_2023_0304.tif --hand
```

Las salidas (parches, modelos, métricas, GeoTIFF) quedan en `Data/procesado/`.

## Alcance

El modelo detecta **dónde había agua en superficie cuando pasó el satélite**. No predice lluvia ni pronostica inundaciones.
