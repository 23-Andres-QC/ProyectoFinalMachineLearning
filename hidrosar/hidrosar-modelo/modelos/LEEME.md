Modelos que usa HidroSAR. En el panel del mapa se elige con cuál evaluar; `MODELO_PT` del `.env` es el predeterminado
(por ejemplo `unet_efficientnet-b0.pt`).

| Archivos | De dónde salen | Qué hacen |
|---|---|---|
| Archivos | Grupo en el selector | De dónde salen | Qué hacen |
|---|---|---|---|
| `unet_cambio_<encoder>.pt` | Deep Learning · Vol1 | `pipeline-final.ipynb` (Kaggle, carpeta `final/modelos/`) | U-Net de 2 canales: imagen de la lluvia y día seco previo. Marcan el agua nueva. Con 2 o más aparece también el **ensamble**, que promedia sus probabilidades. |
| `unet_<encoder>.pt` | Deep Learning · Vol1 | notebook 01 (Kaggle, carpeta `modelos/`) | U-Net de 1 canal: marcan el agua en cada imagen. El agua de lluvia es la que no estaba en los días secos. |
| `vol3/unet_<encoder>.pt` | Deep Learning · Vol2 | carpeta `ModelosVol3` (notebook 01) | U-Net de 1 canal con su umbral, media y desviación dentro del archivo. Mismo uso que `unet_<encoder>.pt`. |
| `vol3/ml_*.joblib` | Machine Learning · Vol2 | carpeta `ModelosVol3` (notebook 01, sección 7) | Machine Learning por píxel a 5 m. Cada archivo trae `{"modelo", "columnas", "umbral"}`; las variables (`hh_media15`, `hh_desv5`, `hh_desv15`, `pendiente`) se calculan del HH suavizado 5×5. |

La carpeta `agua_superficial/` (modelos del `Notebook_Agua_Superficial`) ya no se usa: HidroSAR no la lee.

Umbrales:
- Los de las U-Net van en `umbrales.json` cuando el `.pt` no los trae: `U-Net <encoder>` y `U-Net cambio <encoder>`.
- El del ensamble va como `U-Net cambio ensamble`. Los cinco de cambio son 0.9, elegidos en validación en el pipeline final.
- Los de `vol3/` traen su umbral dentro del archivo.

Los `.pt` de ModelosVol3 venían con la media y la desviación como arreglos de numpy. Se volvieron a guardar como listas
de números para que carguen con `weights_only=True`. La copia `unet_efficientnet-b0 (1).zip` era idéntica y no se copió.

Si un `.pt` de Kaggle llega descomprimido (una carpeta con `data.pkl`, `data/` y `byteorder`), hay que volver a
empaquetarlo como `.pt` antes de copiarlo.

Los modelos no se suben a git: en esta carpeta solo se versiona este LEEME.
