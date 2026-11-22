"""Lectura remota del recorte de una RSLC de NISAR y geocodificación a la grilla de 5 m.

`Remoto` es el mismo lector de descarga_datos.ipynb: h5py pide bytes y Remoto los pide al servidor con la cabecera HTTP
`Range`, así que solo viajan los metadatos y los bloques de HH que cubren el área (nunca la franja completa).
`geocodificar` es `a_grilla` del notebook 01 (sección 3.2), con el recorte calculado antes de leer HH.
"""
import io
import os
import time
from pathlib import Path

import h5py
import numpy as np
import requests
from pyproj import Transformer
from scipy import ndimage
from scipy.interpolate import LinearNDInterpolator

from errores import ErrorProceso


def preparar_credenciales():
    usuario, clave = os.environ.get("EARTHDATA_USER", "").strip(), os.environ.get("EARTHDATA_PASSWORD", "").strip()
    if not usuario or not clave:
        return False
    netrc = Path.home() / ".netrc"
    netrc.write_text(f"machine urs.earthdata.nasa.gov login {usuario} password {clave}\n")
    netrc.chmod(0o600)
    return True


class Remoto(io.RawIOBase):
    def __init__(self, url):
        self.sesion, self.pos, self.bajado = requests.Session(), 0, 0
        r = self._pedir(url, "bytes=0-0")
        self.url, self.n = r.url, int(r.headers["Content-Range"].split("/")[1])

    def _pedir(self, url, rango):
        for intento in range(4):
            try:
                r = self.sesion.get(url, headers={"Range": rango}, timeout=120)
                if r.status_code in (401, 403):
                    raise ErrorProceso("NASA Earthdata rechazó las credenciales (revisa EARTHDATA_USER y EARTHDATA_PASSWORD)")
                r.raise_for_status()
                return r
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if intento == 3:
                    raise
                time.sleep(2 ** intento)

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, pos, desde=0):
        self.pos = [pos, self.pos + pos, self.n + pos][desde]
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        fin = min(self.pos + len(b), self.n)
        if fin <= self.pos:
            return 0
        r = self._pedir(self.url, f"bytes={self.pos}-{fin - 1}")
        b[:len(r.content)] = r.content
        self.pos += len(r.content)
        self.bajado += len(r.content)
        return len(r.content)


def geocodificar(urls, bbox, dem, g):
    """HH (dB, sigma0 calibrado y sin ruido) de una pasada en la grilla g; la pasada puede venir en varios cuadros."""
    o, s, e, n = bbox
    alto, ancho = dem.shape
    cc, ff = np.meshgrid(np.arange(0, ancho, 10), np.arange(0, alto, 10))
    lon, lat = Transformer.from_crs(g["crs"], "EPSG:4326", always_xy=True).transform(
        g["transform"].c + (cc + 0.5) * 5, g["transform"].f - (ff + 0.5) * 5)
    fi, fj = np.meshgrid(np.arange(alto, dtype="float32") / 10, np.arange(ancho, dtype="float32") / 10, indexing="ij")
    hh = np.full(dem.shape, np.nan, "float32")
    bajado = 0
    for url in urls:
        remoto = Remoto(url)
        with h5py.File(io.BufferedReader(remoto, 1 << 22), "r") as f:
            geo, sw = f["science/LSAR/RSLC/metadata/geolocationGrid"], f["science/LSAR/RSLC/swaths"]
            t, r = sw["zeroDopplerTime"][()], sw["frequencyA/slantRange"][()]
            ta, ra = np.meshgrid((geo["zeroDopplerTime"][()] - t[0]) / (t[1] - t[0]),
                                 (geo["slantRange"][()] - r[0]) / (r[1] - r[0]), indexing="ij")
            alturas = geo["heightAboveEllipsoid"][()]
            k0 = int(np.clip(np.searchsorted(alturas, np.nanmin(dem), "right") - 1, 0, len(alturas) - 2))
            k1 = int(np.clip(np.searchsorted(alturas, np.nanmax(dem)), k0 + 1, len(alturas) - 1))
            capas = []
            for k in (k0, k1):
                X, Y = geo["coordinateX"][k], geo["coordinateY"][k]
                m = (X > o - 0.15) & (X < e + 0.15) & (Y > s - 0.15) & (Y < n + 0.15)
                if m.sum() < 4:
                    break
                grueso = LinearNDInterpolator(np.c_[X[m], Y[m]], np.c_[ta[m], ra[m]])(lon, lat).astype("float32")
                capas.append([ndimage.map_coordinates(grueso[..., i], [fi, fj], order=1, mode="nearest") for i in (0, 1)])
            if len(capas) < 2:
                bajado += remoto.bajado
                continue
            w = (dem - alturas[k0]) / (alturas[k1] - alturas[k0])
            az = np.nan_to_num(capas[0][0] + w * (capas[1][0] - capas[0][0]), nan=-9)
            rg = np.nan_to_num(capas[0][1] + w * (capas[1][1] - capas[0][1]), nan=-9)
            nuevo = np.isnan(hh) & (az >= 0) & (az <= len(t) - 1) & (rg >= 0) & (rg <= len(r) - 1)
            if not nuevo.any():
                bajado += remoto.bajado
                continue
            az, rg = az[nuevo], rg[nuevo]
            a0, r0 = int(az.min()), int(rg.min())
            slc = sw["frequencyA/HH"][a0:int(az.max()) + 2, r0:int(rg.max()) + 2].astype("complex64")
            cal = f["science/LSAR/RSLC/metadata/calibrationInformation/geometry"]
            lut, lt, lr = cal["sigma0"][()], cal["zeroDopplerTime"][()], cal["slantRange"][()]
            ruido = f["science/LSAR/RSLC/metadata/calibrationInformation/frequencyA/noiseEquivalentBackscatter"]
            nes, nt, nr = ruido["HH"][()], ruido["zeroDopplerTime"][()], ruido["slantRange"][()]
        bajado += remoto.bajado
        slc[slc == 0] = np.nan
        tiempo, distancia = t[0] + az * (t[1] - t[0]), r[0] + rg * (r[1] - r[0])
        L = ndimage.map_coordinates(lut.astype("float32"), [(tiempo - lt[0]) / (lt[1] - lt[0]), (distancia - lr[0]) / (lr[1] - lr[0])],
                                    order=1, mode="nearest")
        piso = ndimage.map_coordinates(nes.astype("float32"), [(tiempo - nt[0]) / (nt[1] - nt[0]), (distancia - nr[0]) / (nr[1] - nr[0])],
                                       order=1, mode="nearest")
        potencia = ndimage.map_coordinates(np.abs(slc) ** 2, [az - a0, rg - r0], order=1, cval=np.nan, prefilter=False)
        hh[nuevo] = 10 * np.log10(np.maximum(potencia - piso, 0.1 * piso)) - 20 * np.log10(L)
        del slc
    return hh, bajado / 1e6
