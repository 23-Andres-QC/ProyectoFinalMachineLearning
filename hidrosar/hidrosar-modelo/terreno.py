"""Grilla UTM de 5 m del área, DEM Copernicus de 30 m y ESA WorldCover (igual que la sección 3.1 del notebook 01)."""
import numpy as np
import pyproj
import rasterio
import requests
from pyproj import Transformer
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from errores import ErrorProceso

pyproj.network.set_network_enabled(True)
STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
TOKEN = "https://planetarycomputer.microsoft.com/api/sas/v1/token/{}"
GEOIDE = Transformer.from_crs("EPSG:4326+3855", "EPSG:4979", always_xy=True)


def grilla(bbox):
    o, s, e, n = bbox
    lon, lat = (o + e) / 2, (s + n) / 2
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
    xs, ys = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform([o, e, o, e], [s, s, n, n])
    x0, x1 = 5 * np.floor(min(xs) / 5), 5 * np.ceil(max(xs) / 5)
    y0, y1 = 5 * np.floor(min(ys) / 5), 5 * np.ceil(max(ys) / 5)
    return {"crs": f"EPSG:{epsg}", "transform": from_origin(x0, y1, 5, 5),
            "height": int(round((y1 - y0) / 5)), "width": int(round((x1 - x0) / 5))}


def _mosaico(coleccion, bbox):
    o, s, e, n = bbox
    caja = [o - 0.02, s - 0.02, e + 0.02, n + 0.02]
    filtro = {"datetime": "2021-01-01T00:00:00Z/2021-12-31T23:59:59Z"} if coleccion == "esa-worldcover" else {}
    items = requests.post(STAC, json={"collections": [coleccion], "bbox": caja, **filtro}, timeout=120).json()["features"]
    if not items:
        raise ErrorProceso(f"No hay {coleccion} para el área")
    token = requests.get(TOKEN.format(coleccion), timeout=60).json()["token"]
    capa = "map" if coleccion == "esa-worldcover" else "data"
    fuentes = [rasterio.open(f'{i["assets"][capa]["href"]}?{token}') for i in items]
    try:
        arr, transformada = merge(fuentes, bounds=caja)
    finally:
        for f in fuentes:
            f.close()
    return arr[0], transformada


def _en_grilla(coleccion, bbox, g, metodo):
    arr, transformada = _mosaico(coleccion, bbox)
    salida = np.zeros((g["height"], g["width"]), arr.dtype)
    reproject(arr, salida, src_transform=transformada, src_crs="EPSG:4326", dst_transform=g["transform"], dst_crs=g["crs"],
              resampling=metodo)
    return salida


def dem_y_cobertura(bbox, g):
    """DEM en altura elipsoidal (la que usa la grilla de geolocalización de NISAR) y clases de WorldCover (80 = agua)."""
    o, s, e, n = bbox
    geoide = GEOIDE.transform((o + e) / 2, (s + n) / 2, 0)[2]
    dem = _en_grilla("cop-dem-glo-30", bbox, g, Resampling.bilinear).astype("float32") + geoide
    worldcover = _en_grilla("esa-worldcover", bbox, g, Resampling.nearest)
    return dem, worldcover
