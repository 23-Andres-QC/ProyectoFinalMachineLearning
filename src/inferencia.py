"""Inferencia sobre escenas completas (GeoTIFF), capas auxiliares, Otsu, exportación y resumen por distrito."""
import json
from pathlib import Path

import numpy as np, pandas as pd, rasterio, torch
import matplotlib.pyplot as plt
from rasterio.warp import reproject, Resampling
from rasterio.features import rasterize

from . import config as C
from .datos import validos_db
from .entrenamiento import crear_modelo, normalizar, metricas, conteos


def cargar_stats(ruta=C.PREPARADO / "stats.json"):
    return json.load(open(ruta))


def cargar_modelo(modo, encoder, dispositivo, carpeta=C.RESULTADOS / "modelos"):
    modelo = crear_modelo(encoder, modo, pesos=None).to(dispositivo)
    modelo.load_state_dict(torch.load(Path(carpeta) / f"unet_{modo}_{encoder}.pt", map_location=dispositivo))
    return modelo.eval()


def leer_escena(ruta, bandas=(1, 2), lineal=False):
    with rasterio.open(ruta) as s:
        img, perfil = s.read(list(bandas)).astype("float32"), s.profile
    if lineal:
        img = 10 * np.log10(np.clip(img, 1e-6, None))
    return img, perfil


def leer_en_grilla(ruta, perfil, bandas=(1, 2)):
    """Reproyecta otra escena (p. ej. la imagen previa) a la grilla de `perfil`."""
    out = np.full((len(bandas), perfil["height"], perfil["width"]), np.nan, "float32")
    with rasterio.open(ruta) as s:
        for k, b in enumerate(bandas):
            reproject(rasterio.band(s, b), out[k], dst_transform=perfil["transform"], dst_crs=perfil["crs"],
                      resampling=Resampling.bilinear, src_nodata=s.nodata if s.nodata is not None else 0, dst_nodata=np.nan)
    return out


def a_grilla(rutas, perfil, remuestreo=Resampling.bilinear):
    """Mosaico de rásters auxiliares (HAND, JRC, DEM) en la grilla de `perfil`."""
    out = np.full((perfil["height"], perfil["width"]), np.nan, "float32")
    for r in rutas:
        tmp = np.full_like(out, np.nan)
        with rasterio.open(r) as s:
            reproject(rasterio.band(s, 1), tmp, dst_transform=perfil["transform"], dst_crs=perfil["crs"],
                      resampling=remuestreo, dst_nodata=np.nan)
        out = np.where(np.isnan(out), tmp, out)
    return out


def predecir_ventanas(modelo, x, dispositivo, lote=16):
    """Ventana deslizante T×T con paso PASO; promedia las probabilidades solapadas."""
    # Lee cada ventana por separado (x puede ser un memmap) y solo rellena las del borde,
    # para no duplicar la escena completa en RAM.
    _, H, W = x.shape
    Hp = max(H, C.T) + (-max(H, C.T)) % C.PASO
    Wp = max(W, C.T) + (-max(W, C.T)) % C.PASO
    suma, n = np.zeros((H, W), "float32"), np.zeros((H, W), "uint8")
    pos = [(i, j) for i in range(0, Hp - C.T + 1, C.PASO) for j in range(0, Wp - C.T + 1, C.PASO)]

    def ventana(i, j):
        w = np.asarray(x[:, i:i+C.T, j:j+C.T], dtype="float32")
        ph, pw = C.T - w.shape[1], C.T - w.shape[2]
        if ph or pw:
            w = np.pad(w, ((0, 0), (0, ph), (0, pw)), mode="reflect" if min(w.shape[1:]) > max(ph, pw) else "edge")
        return w

    with torch.no_grad(), torch.autocast(dispositivo, enabled=dispositivo == "cuda"):
        for k in range(0, len(pos), lote):
            bloque = pos[k:k + lote]
            v = torch.from_numpy(np.stack([ventana(i, j) for i, j in bloque])).to(dispositivo)
            p = torch.sigmoid(modelo(v).float())[:, 0].cpu().numpy()
            for (i, j), pk in zip(bloque, p):
                h, w = min(C.T, H - i), min(C.T, W - j)
                suma[i:i+h, j:j+w] += pk[:h, :w]
                n[i:i+h, j:j+w] += 1
    return suma / np.maximum(n, 1)


def probabilidad(modelo, modo, stats, post, pre, dispositivo):
    """Construye la entrada del modo (2 o 4 canales) y devuelve (probabilidad, máscara válida)."""
    cfg = C.MODOS[modo]
    valido = validos_db(post)
    if cfg["requiere_pre"]:
        valido &= validos_db(pre)
        img = np.concatenate([pre, post])
    else:
        img = np.concatenate([np.full_like(post, np.nan), post])
    x = normalizar(img[cfg["canales"]], valido, stats, cfg["canales"])
    return predecir_ventanas(modelo, x, dispositivo), valido


def otsu(x, bins=256):
    h, b = np.histogram(np.clip(x, C.DB_MIN, C.DB_MAX), bins=bins)
    c = (b[:-1] + b[1:]) / 2
    p = h / h.sum()
    w, mu = np.cumsum(p), np.cumsum(p * c)
    return c[np.nanargmax((mu[-1] * w - mu) ** 2 / (w * (1 - w) + 1e-12))]


def evaluar_mascaras(capas, ref, valido):
    """capas: {nombre: bool HxW}; ref: int HxW con -1 = fuera del área evaluable."""
    m = valido & (ref != -1)
    r = ref[m] == 1
    return pd.DataFrame([{"metodo": k, "agua_%": 100 * p[m].mean(), **metricas(*conteos(p[m], r))}
                         for k, p in capas.items()])


def guardar_tif(ruta, arr, perfil, dtype, nodata):
    p = perfil.copy()
    p.update(count=1, dtype=dtype, nodata=nodata, compress="deflate", driver="GTiff")
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(ruta, "w", **p) as d:
        d.write(arr.astype(dtype), 1)


def rasterizar(gdf, perfil, valor=1):
    gdf = gdf.to_crs(perfil["crs"])
    return rasterize(((g, valor) for g in gdf.geometry.force_2d()), (perfil["height"], perfil["width"]),
                     transform=perfil["transform"], fill=0, dtype="uint8")


def resumen_por_distrito(mascara, valido, perfil, distritos, provincia="LIMA"):
    """km² y % de área detectada por distrito. `distritos`: GeoDataFrame con NOMBDIST/NOMBPROV."""
    d = distritos[distritos.NOMBPROV == provincia].to_crs(perfil["crs"])
    km2_px = abs(perfil["transform"].a * perfil["transform"].e) / 1e6
    filas = []
    for _, fila in d.iterrows():
        zona = rasterize([(fila.geometry, 1)], (perfil["height"], perfil["width"]),
                         transform=perfil["transform"], fill=0, dtype="uint8").astype(bool) & valido
        if zona.sum() == 0:
            continue
        det = (mascara & zona).sum()
        filas.append({"distrito": fila.NOMBDIST, "km2_observados": zona.sum() * km2_px,
                      "km2_detectados": det * km2_px, "%_detectado": 100 * det / zona.sum()})
    return pd.DataFrame(filas).sort_values("km2_detectados", ascending=False).reset_index(drop=True)


def mostrar(paneles, titulo="", max_lado=1500):
    """paneles: lista de (array, título, cmap, vmin, vmax)."""
    fig, ejes = plt.subplots(1, len(paneles), figsize=(4 * len(paneles), 4))
    for ax, (z, t, cmap, vmin, vmax) in zip(np.atleast_1d(ejes), paneles):
        r = max(1, max(z.shape) // max_lado)
        ax.imshow(z[::r, ::r], cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
        ax.set_title(f"{titulo} · {t}" if titulo else t, fontsize=8)
        ax.axis("off")
    plt.tight_layout()
    plt.show()
