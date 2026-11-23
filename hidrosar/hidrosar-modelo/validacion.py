"""Validaciones de los modelos entrenados (Vol1 y ModelosVol3) en las escenas de validación de los notebooks.

Se usan los recortes NISAR que ya están en Data/crudos_nisar (montado en /crudos, solo lectura): no se descarga nada de la
ASF. Cada escena es una zona fija de la ciudad. Por cada escena y modelo se compara lo que marca el modelo con la referencia
y se devuelven tres capas de polígonos para el mapa:
- aciertos: agua que marcan el modelo y la referencia;
- falsas alarmas: agua que marca el modelo y la referencia no;
- omisiones: agua de la referencia que el modelo no marca.

Referencia:
- U-Net de agua y Machine Learning (ModelosVol3): la etiqueta de finalvol1.ipynb (sección 3.4). HH suavizado 5 × 5 bajo el
  umbral calibrado con el agua permanente de WorldCover, en terreno plano, sin manchas de menos de 40 píxeles. En el día
  seco, solo el agua permanente de WorldCover.
- U-Net de cambio (Vol1): la regla de pipeline-final.ipynb. HH al menos 3 dB por debajo del día seco de la misma órbita, en
  terreno plano, sin agua permanente ni zonas que ya son oscuras en seco, sin manchas de menos de 10 píxeles. Solo en las
  escenas que tienen un día seco de la misma órbita.
"""
import os
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import ndimage

from errores import ErrorProceso
from modelos import AguaPixelML, catalogo
from nisar import geocodificar
from segmentacion import entrada_cambio, sin_manchas_chicas, suave, vectorizar
from terreno import dem_y_cobertura, grilla

CRUDOS = Path(os.environ.get("CRUDOS_DIR", "/crudos"))
CAIDA_DB = -3.0           # regla de cambio del pipeline final
UMBRAL_RESPALDO = -14.0   # mediana de los umbrales de las lluvias en finalvol1.ipynb, si la zona no tiene agua permanente
MINIMO_DIBUJO = 10        # en el mapa no se dibujan manchas de menos de 10 píxeles (250 m²)
TOLERANCIA_M = 5.0        # simplificación de los polígonos (1 píxel)

# Solo se valida el mejor modelo de cada grupo, el que eligió la validación de su notebook:
# - Deep Learning · Vol1: el ensamble de las U-Net de cambio («mejor modelo» de pipeline-final.ipynb);
# - Deep Learning · Vol2: la U-Net efficientnet-b0 (la de mayor IoU en validación de finalvol1.ipynb);
# - Machine Learning · Vol2: el Random Forest + pendiente (el de mayor IoU en validación entre los de ML de finalvol1.ipynb).
MODELOS = ["unet_cambio_ensamble", "vol3/unet_efficientnet-b0", "vol3/ml_random_forest_pendiente"]

ESCENAS = [
    {"clave": "iquitos_2026-09-04", "ciudad": "iquitos", "lugar": "Iquitos", "pista": "155_D", "fecha": "20260904",
     "seco": "20260624", "dia": "lluvia", "origen": "Validación de finalvol1.ipynb",
     "bbox": (-73.30, -3.80, -73.22, -3.70)},
    {"clave": "iquitos_2026-10-22", "ciudad": "iquitos", "lugar": "Iquitos", "pista": "155_D", "fecha": "20261022",
     "seco": "20260624", "dia": "lluvia", "origen": "Validación de finalvol1.ipynb",
     "bbox": (-73.30, -3.80, -73.22, -3.70)},
    {"clave": "iquitos_2026-06-24", "ciudad": "iquitos", "lugar": "Iquitos", "pista": "155_D", "fecha": "20260624",
     "seco": None, "dia": "seco", "origen": "Validación de finalvol1.ipynb (día seco)",
     "bbox": (-73.30, -3.80, -73.22, -3.70)},
    {"clave": "concepcion_2026-09-24", "ciudad": "concepcion", "lugar": "Concepción", "pista": "097_D",
     "fecha": "20260924", "seco": "20260819", "dia": "lluvia", "origen": "Validación de finalvol1.ipynb",
     "bbox": (-73.13, -36.88, -73.02, -36.79)},
    {"clave": "puerto_montt_2026-07-15", "ciudad": "puerto_montt", "lugar": "Puerto Montt", "pista": "104_A",
     "fecha": "20260715", "seco": None, "dia": "lluvia", "origen": "Validación de finalvol1.ipynb",
     "bbox": (-73.00, -41.49, -72.88, -41.44)},
    {"clave": "lima_sur_2026-11-05", "ciudad": "lima", "lugar": "Lima Sur", "pista": "003_A", "fecha": "20261105",
     "seco": "20260825", "dia": "lluvia", "origen": "Evento de pipeline-final.ipynb y prueba de finalvol1.ipynb",
     "bbox": (-77.04, -12.25, -76.89, -12.16)},
]
_ESCENA = {e["clave"]: e for e in ESCENAS}


def _fecha(aaaammdd):
    return f"{aaaammdd[:4]}-{aaaammdd[4:6]}-{aaaammdd[6:]}"


def _archivos(e, fecha):
    """Cuadros de la pasada (misma pista y fecha) en Data/crudos_nisar/<ciudad>/."""
    return [str(p) for p in sorted((CRUDOS / e["ciudad"]).glob(f"NISAR_*_{e['pista']}_*_{fecha}T*.h5"))]


def escenas():
    """Las escenas de validación, con lo que hace falta para listarlas y dibujar su zona."""
    lista = []
    for e in ESCENAS:
        dias = [e["fecha"]] + ([e["seco"]] if e["seco"] else [])
        lista.append({"clave": e["clave"], "lugar": e["lugar"], "fecha": _fecha(e["fecha"]), "dia": e["dia"],
                      "pista": e["pista"].replace("_", " "), "seco": _fecha(e["seco"]) if e["seco"] else None,
                      "origen": e["origen"], "bbox": list(e["bbox"]), "cambio": bool(e["seco"]),
                      "disponible": all(_archivos(e, d) for d in dias)})
    return lista


def modelos():
    """Los modelos que se validan (de `MODELOS`, los que estén en el catálogo), en ese orden."""
    lista = {m["id"]: m for m in catalogo()}
    return [{k: lista[i][k] for k in ("id", "nombre", "familia", "tipo")} for i in MODELOS if i in lista]


def _umbral_wc(s, valido, plano, wc):
    """Umbral que mejor separa el agua permanente de WorldCover de la tierra (`umbral_wc` de finalvol1.ipynb)."""
    agua = plano & valido & (wc == 80)
    tierra = plano & valido & np.isin(wc, [10, 20, 30, 40, 50, 60, 70, 100])
    if agua.sum() < 1000 or tierra.sum() < 1000:
        return None
    rng = np.random.default_rng(0)
    a = s[agua][rng.choice(agua.sum(), 200_000)]
    b = s[tierra][rng.choice(tierra.sum(), 200_000)]
    candidatos = np.arange(-30, -9.9, 0.25)
    equilibrio = [0.5 * ((a < c).mean() + (b >= c).mean()) for c in candidatos]
    return float(candidatos[int(np.argmax(equilibrio))])


def _etiqueta(e, s, valido, dem, wc):
    """Etiqueta del mismo día de finalvol1.ipynb (sección 3.4)."""
    if e["dia"] == "seco":
        return valido & (wc == 80)
    plano = valido & (AguaPixelML._pendiente(dem) < 5)
    umbral = _umbral_wc(s, valido, plano, wc)
    agua = ndimage.binary_opening((s < (UMBRAL_RESPALDO if umbral is None else umbral)) & plano, iterations=2)
    manchas, _ = ndimage.label(agua)
    return agua & (np.bincount(manchas.ravel())[manchas] >= 40)


@lru_cache(maxsize=1)
def _zona(clave):
    """Todo lo que comparten los modelos en una escena: grilla, relieve, imágenes y referencias. Se guarda la última escena
    en memoria porque el backend pide sus modelos uno tras otro."""
    e = _ESCENA[clave]
    lluvia = _archivos(e, e["fecha"])
    if not lluvia:
        raise ErrorProceso(f"No está el recorte NISAR del {_fecha(e['fecha'])} en Data/crudos_nisar/{e['ciudad']}")
    bbox = e["bbox"]
    g = grilla(bbox)
    dem, wc = dem_y_cobertura(bbox, g)
    hh, _ = geocodificar(lluvia, bbox, dem, g)
    valido = np.isfinite(hh)
    if valido.mean() < 0.01:
        raise ErrorProceso("La pasada no tiene datos del radar en la zona de validación")
    s = suave(hh)
    z = {"g": g, "dem": dem, "hh": hh, "s": s, "valido": valido, "etiqueta": _etiqueta(e, s, valido, dem, wc)}
    if e["seco"]:
        seco = _archivos(e, e["seco"])
        if not seco:
            raise ErrorProceso(f"No está el recorte NISAR del día seco {_fecha(e['seco'])} en Data/crudos_nisar/{e['ciudad']}")
        hh_seco, _ = geocodificar(seco, bbox, dem, g)
        x2, evaluable, cambio = entrada_cambio(hh, [(e["seco"], hh_seco)], e["fecha"], wc, dem)
        with np.errstate(invalid="ignore"):
            regla = ndimage.binary_opening(evaluable & (cambio < CAIDA_DB))
        z |= {"x2": x2, "evaluable": evaluable, "regla": sin_manchas_chicas(regla)}
    return z


def validar(clave, modelo_id, modelos):
    """Aciertos, falsas alarmas y omisiones de un modelo en una escena, como polígonos en lat/lon."""
    if clave not in _ESCENA:
        raise ErrorProceso("Esa escena de validación no existe")
    if modelo_id not in MODELOS:
        raise ErrorProceso("Solo se valida el mejor modelo de cada grupo")
    inicio = time.time()
    e = _ESCENA[clave]
    info, modelo = modelos.obtener(modelo_id)
    if info["tipo"] == "cambio" and not e["seco"]:
        raise ErrorProceso(f"«{info['nombre']}» necesita un día seco de la misma órbita y esta escena no lo tiene")
    z = _zona(clave)
    if info["tipo"] == "cambio":
        zona, referencia = z["evaluable"], z["regla"]
        marcado = (modelo.probabilidad(z["x2"]) >= modelo.umbral) & zona
        s = e["seco"]
        texto = f"la regla de cambio de pipeline-final.ipynb frente al día seco del {s[6:]}/{s[4:6]}/{s[:4]}"
    else:
        zona, referencia = z["valido"], z["etiqueta"]
        marcado = modelo.agua(z["hh"], z["s"], z["dem"]) & zona
        texto = ("el agua permanente de WorldCover (día seco)" if e["dia"] == "seco"
                 else "la etiqueta del mismo día de finalvol1.ipynb")
    capas = {"aciertos": marcado & referencia, "falsas": marcado & ~referencia & zona, "omisiones": referencia & ~marcado}
    salida = {"escena": clave, "modelo": info["id"], "bbox": list(e["bbox"]), "referencia": texto}
    for nombre, m in capas.items():
        salida[nombre] = vectorizar(sin_manchas_chicas(m, MINIMO_DIBUJO), z["g"], e["bbox"], TOLERANCIA_M)[0]
    salida["segundos"] = round(time.time() - inicio, 1)
    return salida
