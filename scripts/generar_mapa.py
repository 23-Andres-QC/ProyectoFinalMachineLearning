"""Mapa web (HTML con Leaflet) de las detecciones de agua de Lima Sur 2023 sobre un mapa base.

Lee los GeoTIFF que exporta la sección 11 del notebook (Data/procesado/resultados/predicciones/) y genera un único
HTML autocontenido con las capas superpuestas:
  - agua (modo `agua`, 2 canales, filtrada con HAND y JRC)
  - inundación nueva (modo `cambio`, 4 canales) y un punto por cada mancha detectada
  - probabilidad de agua del modelo de 2 canales
  - distritos de Lima con el área detectada (lima_2023_por_distrito.csv)

Uso:  python scripts/generar_mapa.py [--salida Data/procesado/resultados/mapa_agua_lima_2023.html]
"""
import sys, io, json, base64, argparse, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore", message=".*Measured \\(M\\) geometry.*")

import numpy as np, pandas as pd, rasterio, geopandas as gpd
from PIL import Image
from rasterio.warp import calculate_default_transform, reproject, transform as transformar, Resampling
from scipy import ndimage

from src import config as C

PRED = C.RESULTADOS / "predicciones"
ESCENA = "lima_2023_0316"
WEB = "EPSG:3857"


def a_web(ruta, remuestreo, factor=1):
    """Reproyecta un GeoTIFF a Web Mercator (para que calce con las teselas) y devuelve (array, límites lat/lon)."""
    with rasterio.open(ruta) as s:
        t, w, h = calculate_default_transform(s.crs, WEB, s.width // factor, s.height // factor, *s.bounds)
        out = np.full((h, w), s.nodata, s.dtypes[0])
        reproject(rasterio.band(s, 1), out, dst_transform=t, dst_crs=WEB, resampling=remuestreo,
                  src_nodata=s.nodata, dst_nodata=s.nodata)
    x0, y1 = t * (0, 0)
    x1, y0 = t * (w, h)
    lon, lat = transformar(WEB, "EPSG:4326", [x0, x1], [y0, y1])
    return out, [[lat[0], lon[0]], [lat[1], lon[1]]]


def png(indices, paleta):
    """indices: uint8 HxW; paleta: lista de (r, g, b, a) por índice. Devuelve un data URI PNG con paleta."""
    img = Image.fromarray(indices, "P")
    img.putpalette([c for rgba in paleta for c in rgba[:3]])
    img.info["transparency"] = bytes(rgba[3] for rgba in paleta)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True, transparency=bytes(rgba[3] for rgba in paleta))
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def capa_mascara(ruta, color):
    m, limites = a_web(ruta, Resampling.nearest)
    return png(np.where(m == 1, 1, 0).astype("uint8"), [(0, 0, 0, 0), color]), limites, m


def capa_probabilidad(ruta, desde=0.3, niveles=48):
    p, limites = a_web(ruta, Resampling.bilinear, factor=2)
    k = np.clip((p - desde) / (1 - desde), 0, 1)
    idx = np.where(p >= desde, 1 + np.round(k * (niveles - 1)), 0).astype("uint8")
    # rampa amarillo → verde azulado → azul oscuro, cada vez más opaca
    anclas = np.array([[253, 231, 37], [33, 145, 140], [59, 82, 139], [68, 1, 84]], float)
    paleta = [(0, 0, 0, 0)]
    for i in range(niveles):
        f = i / (niveles - 1) * (len(anclas) - 1)
        j = min(int(f), len(anclas) - 2)
        r, g, b = anclas[j] + (anclas[j + 1] - anclas[j]) * (f - j)
        paleta.append((int(r), int(g), int(b), int(90 + 140 * i / (niveles - 1))))
    return png(idx, paleta), limites


def manchas_inundacion(ruta):
    """Un punto (lat, lon, m²) por cada componente conexa de la máscara de inundación nueva."""
    with rasterio.open(ruta) as s:
        m, t, crs = s.read(1) == 1, s.transform, s.crs
    etiquetas, n = ndimage.label(m, structure=np.ones((3, 3)))
    if n == 0:
        return []
    idx = np.arange(1, n + 1)
    centros = ndimage.center_of_mass(m, etiquetas, idx)
    px = ndimage.sum(m, etiquetas, idx)
    xs, ys = zip(*[t * (c + 0.5, f + 0.5) for f, c in centros])
    lon, lat = transformar(crs, "EPSG:4326", xs, ys)
    m2_px = abs(t.a * t.e)
    return sorted(([round(a, 6), round(o, 6), round(float(k) * m2_px)] for a, o, k in zip(lat, lon, px)),
                  key=lambda r: -r[2])


def distritos(ruta_escena):
    with rasterio.open(ruta_escena) as s:
        b = s.bounds
    d = gpd.read_file(C.PRUEBAS / "distritos_lima.gpkg")
    d = d.cx[b.left:b.right, b.bottom:b.top]
    res = pd.read_csv(C.RESULTADOS / "lima_2023_por_distrito.csv")
    d = d[["NOMBDIST", "geometry"]].rename(columns={"NOMBDIST": "distrito"}).merge(res, on="distrito", how="inner")
    d["geometry"] = d.geometry.force_2d().simplify(25)
    d = d.rename(columns={"%_detectado": "pct_inundacion", "km2_detectados": "km2_inundacion"}).round(4)
    return json.loads(d.to_crs("EPSG:4326").to_json())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=str(C.RESULTADOS / f"mapa_agua_{ESCENA.rsplit('_', 1)[0]}.html"))
    a = ap.parse_args()

    agua_png, limites, agua = capa_mascara(PRED / f"{ESCENA}_agua.tif", (30, 136, 229, 215))
    inund_png, _, inund = capa_mascara(PRED / f"{ESCENA}_inundacion.tif", (229, 57, 53, 255))
    sin_pre_png = png(np.where(inund == 255, 1, 0).astype("uint8"), [(0, 0, 0, 0), (120, 120, 120, 70)])
    prob_png, limites_prob = capa_probabilidad(PRED / f"{ESCENA}_prob_agua.tif")
    manchas = manchas_inundacion(PRED / f"{ESCENA}_inundacion.tif")

    with rasterio.open(PRED / f"{ESCENA}_agua.tif") as s:
        m = s.read(1)
        km2_px = abs(s.transform.a * s.transform.e) / 1e6
    with rasterio.open(PRED / f"{ESCENA}_inundacion.tif") as s:
        n = s.read(1)
    resumen = {"km2_agua": round(float((m == 1).sum() * km2_px), 2),
               "pct_agua": round(float(100 * (m == 1).sum() / (m != 255).sum()), 2),
               "km2_inundacion": round(float((n == 1).sum() * km2_px), 3),
               "pct_inundacion": round(float(100 * (n == 1).sum() / (n != 255).sum()), 3),
               "manchas": len(manchas)}

    datos = {"limites": limites, "limites_prob": limites_prob, "agua": agua_png, "inundacion": inund_png,
             "sin_pre": sin_pre_png, "prob": prob_png, "manchas": manchas, "distritos": distritos(PRED / f"{ESCENA}_agua.tif"),
             "resumen": resumen}
    html = (Path(__file__).with_name("plantilla_mapa.html").read_text(encoding="utf-8")
            .replace("/*__DATOS__*/null", json.dumps(datos, ensure_ascii=False)))
    Path(a.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.salida).write_text(html, encoding="utf-8")
    print(f"{a.salida} · {len(html) / 1e6:.1f} MB · agua {resumen['km2_agua']} km² · "
          f"inundación nueva {resumen['km2_inundacion']} km² en {len(manchas)} manchas")


if __name__ == "__main__":
    main()
