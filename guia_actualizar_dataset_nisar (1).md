# Guía: agregar el evento de lluvia del 11 de septiembre al dataset NISAR de Lima Sur

**Proyecto:** detectar agua de lluvia en Lima Sur comparando la imagen **del evento** con la mediana de los **días secos de la misma órbita** (detección de cambio). Con eso se generan etiquetas automáticas para entrenar U-Net y modelos de ML.

**Eventos con pase de NISAR poco después de la lluvia:**

| Evento | Lluvia | Pase NISAR (hora Lima) | Órbita | ¿Está en el dataset? |
|---|---|---|---|---|
| A | 4 nov 16:00 → 5 nov 06:00 (10.4 mm, récord) | **5 nov, 5:58 am** (al terminar la lluvia) | 003 A | ✅ `hh_20261105.tif` |
| B | noche 10 → madrugada 11 sep 2026 | **11 sep, 6:25 pm** (~12–15 h después) | 083 D | ❌ **falta** |
| C | 16–17 ago 2026 | 18 ago, 6:25 pm (~2 días) | 083 D | ✅ `hh_20260818.tif` |

Los días secos de referencia de ambas órbitas ya están en el dataset, así que **solo falta el 11 de septiembre**.

> Todo debe quedar **en el mismo formato y la misma grilla** que el dataset actual `andres4499/dataaaaaaaa`, y subirse **como nueva versión de ese mismo dataset**.

---

## 1. Descargar

Necesitas una cuenta gratuita de **NASA Earthdata**: https://urs.earthdata.nasa.gov

### Obligatorio: 11 de septiembre (órbita 083 D, dos marcos)
```
NISAR_L1_PR_RSLC_030_083_D_094_2005_SHSH_M_20260911T232519_20260911T232553_P05023_N_F_J_001.h5
NISAR_L1_PR_RSLC_030_083_D_095_2005_SHSH_A_20260911T232552_20260911T232608_P05023_N_P_J_001.h5
```

### Recomendado: días secos posteriores, como referencia extra
```
NISAR_L1_PR_RSLC_031_083_D_094_2005_DHDH_M_20260923T232519_20260923T232553_P05023_N_F_J_001.h5
NISAR_L1_PR_RSLC_031_083_D_095_2005_DHDH_A_20260923T232552_20260923T232600_P05023_N_P_J_001.h5
NISAR_L1_PR_RSLC_036_003_A_171_2005_DHDH_A_20261117T105845_20261117T105902_P05036_N_P_J_001.h5
```

### URLs directas (ASF)
```
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_PROVISIONAL_V1/NISAR_L1_PR_RSLC_030_083_D_094_2005_SHSH_M_20260911T232519_20260911T232553_P05023_N_F_J_001/NISAR_L1_PR_RSLC_030_083_D_094_2005_SHSH_M_20260911T232519_20260911T232553_P05023_N_F_J_001.h5
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_PROVISIONAL_V1/NISAR_L1_PR_RSLC_030_083_D_095_2005_SHSH_A_20260911T232552_20260911T232608_P05023_N_P_J_001/NISAR_L1_PR_RSLC_030_083_D_095_2005_SHSH_A_20260911T232552_20260911T232608_P05023_N_P_J_001.h5
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_PROVISIONAL_V1/NISAR_L1_PR_RSLC_031_083_D_094_2005_DHDH_M_20260923T232519_20260923T232553_P05023_N_F_J_001/NISAR_L1_PR_RSLC_031_083_D_094_2005_DHDH_M_20260923T232519_20260923T232553_P05023_N_F_J_001.h5
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_PROVISIONAL_V1/NISAR_L1_PR_RSLC_031_083_D_095_2005_DHDH_A_20260923T232552_20260923T232600_P05023_N_P_J_001/NISAR_L1_PR_RSLC_031_083_D_095_2005_DHDH_A_20260923T232552_20260923T232600_P05023_N_P_J_001.h5
https://nisar.asf.earthdatacloud.nasa.gov/NISAR/NISAR_L1_RSLC_V1/NISAR_L1_PR_RSLC_036_003_A_171_2005_DHDH_A_20261117T105845_20261117T105902_P05036_N_P_J_001/NISAR_L1_PR_RSLC_036_003_A_171_2005_DHDH_A_20261117T105845_20261117T105902_P05036_N_P_J_001.h5
```

**Formas de descargar:** ASF Vertex (https://search.asf.alaska.edu), buscando el nombre; tu notebook `descarga_datos.ipynb`, agregando estos nombres; o Python con un token de Earthdata:
```python
import requests, os
TOKEN = os.environ["EARTHDATA_TOKEN"]          # no lo pegues en un notebook público
for url in open("urls.txt").read().split():
    nombre = url.rsplit("/", 1)[1]
    with requests.get(url, headers={"Authorization": f"Bearer {TOKEN}"}, stream=True) as r:
        r.raise_for_status()
        with open(nombre, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
    print("ok", nombre)
```
Cada archivo pesa aproximadamente entre 0.5 y 1 GB.

---

## 2. Procesar (solo intensidad HH, con el mismo código del dataset actual)

| Salida | Obligatorio |
|---|---|
| `procesado/nisar/lima/hh_20260911.tif` | ✅ |
| `procesado/nisar/lima/hh_20260923.tif` | recomendado |
| `procesado/nisar/lima/hh_20261117.tif` | recomendado |

**Reglas:**
1. **Misma grilla** que `hh_20261024.tif`: mismo CRS, misma transformada y mismas filas y columnas (UTM, 5 m).
2. **HH en dB**, con `NaN` fuera de la cobertura, igual que los `hh_*.tif` actuales.
3. **Órbita 083: mosaico de los marcos 094 y 095**, igual que en las otras fechas de esa órbita.
4. Solo el canal HH (el 11 de septiembre es SHSH y el resto DHDH; ignora HV).
5. Copia los `.h5` nuevos en `crudos_nisar/lima/`.
6. **No hace falta generar etiqueta ni `slc_*.npy`.** Las etiquetas por detección de cambio se calculan en el notebook.

---

## 3. Verificar antes de subir

```python
import numpy as np, rasterio
from pathlib import Path
P = Path("Data/procesado/nisar/lima")          # ajusta la ruta
ref = rasterio.open(P / "hh_20261024.tif")
for f in ["20260911", "20260923", "20261117"]:
    p = P / f"hh_{f}.tif"
    if not p.exists():
        print("falta", p.name); continue
    t = rasterio.open(p)
    assert t.crs == ref.crs and t.transform == ref.transform and t.shape == ref.shape, f"grilla distinta en {p.name}"
    hh = t.read(1)
    print(f"{p.name}: OK | cobertura {np.isfinite(hh).mean():.0%} | mediana {np.nanmedian(hh):.1f} dB")
```
Valores esperados: la mediana debe estar entre unos −10 y −5 dB, como en las demás fechas, y la cobertura debe ser parecida a la de `hh_20260830.tif`.

---

## 4. Subir a Kaggle

1. Abre `andres4499/dataaaaaaaa` → **New Version**.
2. Agrega `hh_20260911.tif` (y los recomendados) en `Data/procesado/nisar/lima/`, y los `.h5` en `Data/crudos_nisar/lima/`.
3. **No borres ni renombres** nada de lo que ya existe.
4. Nota de la versión: *"v2: evento de lluvia del 11-sep-2026 (órbita 083)"*.

## Checklist
- [ ] 2 `.h5` del 11 de septiembre descargados (más 3 recomendados).
- [ ] `hh_20260911.tif` con la misma grilla que los anteriores.
- [ ] El script de verificación pasa sin errores.
- [ ] Subido como **nueva versión** de `andres4499/dataaaaaaaa`.
