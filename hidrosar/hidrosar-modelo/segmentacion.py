"""U-Net entrenada en Kaggle, agua de lluvia (secciones 8.3 y 10 del notebook 01) y polígonos livianos para guardar."""
import json
import warnings
from pathlib import Path

import numpy as np
import segmentation_models_pytorch as smp
import shapely
import torch
from pyproj import Transformer
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import MultiPolygon, box, mapping, shape

from errores import ErrorProceso

warnings.filterwarnings("ignore", message="All-NaN slice")
warnings.filterwarnings("ignore", message="Mean of empty slice")
DISPOSITIVO = "cuda" if torch.cuda.is_available() else "cpu"


def suave(hh, n=5):
    valido = np.isfinite(hh)
    return np.where(valido, ndimage.median_filter(np.where(valido, hh, -40), size=n, mode="nearest"), np.nan).astype("float32")


def umbral_de(guardado, ruta, encoder):
    """El .pt del notebook 01 trae su umbral; los de la corrida anterior lo tienen aparte en umbrales.json (tablas/)."""
    if guardado.get("umbral") is not None:
        return float(guardado["umbral"])
    archivo = Path(ruta).with_name("umbrales.json")
    if archivo.exists():
        umbrales = json.loads(archivo.read_text(encoding="utf-8"))
        if f"U-Net {encoder}" in umbrales:
            return float(umbrales[f"U-Net {encoder}"])
    raise ErrorProceso(f"El modelo {Path(ruta).name} no trae su umbral: copia umbrales.json (carpeta tablas/ de Kaggle) "
                       "en hidrosar-modelo/modelos/")


class ModeloUNet:
    def __init__(self, ruta):
        # weights_only: carga solo tensores y datos simples, sin ejecutar código guardado en el archivo
        guardado = torch.load(ruta, map_location="cpu", weights_only=True)
        self.encoder = guardado.get("encoder", "resnet34")
        self.umbral = umbral_de(guardado, ruta, self.encoder)
        self.red = smp.Unet(self.encoder, encoder_weights=None, in_channels=1, classes=1)
        self.red.load_state_dict(guardado["pesos"])
        self.red.to(DISPOSITIVO).eval()
        self.media = float(np.asarray(guardado["media"]).ravel()[0])
        self.desv = float(np.asarray(guardado["desv"]).ravel()[0])

    def probabilidad(self, s):
        """Probabilidad de agua por píxel: ventana de 256 con paso de 128 y pesos gaussianos en los solapes."""
        x = np.nan_to_num((np.clip(s, -35, 10) - self.media) / self.desv).astype("float32")
        alto0, ancho0 = x.shape
        alto, ancho = max(alto0, 256), max(ancho0, 256)
        x = np.pad(x, ((0, alto - alto0), (0, ancho - ancho0)))
        g = np.exp(-(np.arange(256) - 127.5) ** 2 / (2 * 32.0 ** 2)).astype("float32")
        peso = np.outer(g, g)
        suma, veces = np.zeros((alto, ancho), "float32"), np.zeros((alto, ancho), "float32")
        filas = sorted(set(range(0, alto - 256, 128)) | {alto - 256})
        columnas = sorted(set(range(0, ancho - 256, 128)) | {ancho - 256})
        with torch.no_grad():
            for i in filas:
                lote = torch.from_numpy(np.stack([x[None, i:i + 256, j:j + 256] for j in columnas])).to(DISPOSITIVO)
                prob = torch.sigmoid(self.red(lote)).float().cpu().numpy()[:, 0]
                for j, pj in zip(columnas, prob):
                    suma[i:i + 256, j:j + 256] += pj * peso
                    veces[i:i + 256, j:j + 256] += peso
        return (suma / veces)[:alto0, :ancho0]

    def agua(self, s):
        return (self.probabilidad(s) >= self.umbral) & np.isfinite(s)


def limpia(m, minimo=40):
    m = ndimage.binary_opening(m, iterations=1)
    manchas, _ = ndimage.label(m)
    return m & (np.bincount(manchas.ravel())[manchas] >= minimo)


def sin_agua_grande(m, seco, minimo_km2=0.05, borde=3):
    manchas, _ = ndimage.label(seco)
    grande = (np.bincount(manchas.ravel()) * 25 / 1e6 >= minimo_km2)[manchas] & seco
    grande = ndimage.binary_dilation(grande, iterations=borde)
    nuevas, _ = ndimage.label(m)
    tocan = np.unique(nuevas[grande & m])
    return m & ~np.isin(nuevas, tocan[tocan > 0])


def agua_de_lluvia(modelo, hh_lluvia, hh_referencias, worldcover):
    """Agua de la U-Net el día de la lluvia que no es agua en los días secos ni agua permanente, con HH al menos 3 dB más bajo
    que la mediana seca, sin manchas chicas y sin las que tocan un cuerpo de agua grande del día seco."""
    s = suave(hh_lluvia)
    agua = modelo.agua(s)
    permanente = worldcover == 80
    mar = ndimage.binary_dilation(permanente, iterations=2)
    if not hh_referencias:
        return sin_agua_grande(limpia(agua & ~mar), permanente), "sin_referencia"
    secos = [suave(h) for h in hh_referencias]
    muestra = np.random.default_rng(0).choice(s.size, min(2_000_000, s.size))
    nivel_seco = np.median([np.nanmedian(x.flat[muestra]) for x in secos])
    s = s - (np.nanmedian(s.flat[muestra]) - nivel_seco)
    dif = s - np.nanmedian(np.stack(secos), 0)
    veces = sum(modelo.agua(x).astype("uint8") for x in secos)
    seco = (veces > 0.2 * len(secos)) | permanente
    m = sin_agua_grande(limpia(agua & ~seco & ~mar & (dif < -3)), seco)
    return m, f"cambio_vs_{len(secos)}_referencias"


def vectorizar(m, g, bbox):
    """Polígonos del agua de lluvia en lat/lon: simplificados a 2.5 m (la mitad del píxel), recortados al área y con
    coordenadas redondeadas a 1e-6° (~0.1 m). Es lo único que se guarda."""
    if not m.any():
        return None, 0, 0.0
    a_utm = Transformer.from_crs("EPSG:4326", g["crs"], always_xy=True)
    a_geo = Transformer.from_crs(g["crs"], "EPSG:4326", always_xy=True)
    caja = shapely.transform(shapely.segmentize(box(*bbox), 0.001), lambda xy: np.column_stack(a_utm.transform(xy[:, 0], xy[:, 1])))
    etiquetas, _ = ndimage.label(m)
    poligonos = []
    for geom, _ in shapes(etiquetas.astype("int32"), mask=m, transform=g["transform"]):
        p = shape(geom).simplify(2.5, preserve_topology=True).intersection(caja)
        poligonos += [q for q in getattr(p, "geoms", [p]) if q.geom_type == "Polygon" and not q.is_empty]
    if not poligonos:
        return None, 0, 0.0
    area = float(sum(p.area for p in poligonos))
    multi = shapely.transform(MultiPolygon(poligonos), lambda xy: np.column_stack(a_geo.transform(xy[:, 0], xy[:, 1])))
    return mapping(shapely.set_precision(multi, 1e-6)), len(poligonos), round(area, 1)
