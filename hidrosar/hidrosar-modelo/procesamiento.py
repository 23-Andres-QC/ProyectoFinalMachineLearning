import logging
import os
import time
from pathlib import Path

import numpy as np

from errores import ErrorProceso
from nisar import geocodificar, preparar_credenciales
from segmentacion import DISPOSITIVO, ModeloUNet, agua_de_lluvia, vectorizar
from terreno import dem_y_cobertura, grilla

COBERTURA_MINIMA = 0.2


class Procesador:
    def __init__(self):
        self.ruta = Path(os.environ.get("MODELO_PT", "/modelos/unet_resnet34.pt"))
        self.credenciales = preparar_credenciales()
        self.modelo = None

    def estado(self):
        return {"disponible": True, "modelo": self.ruta.name, "modelo_encontrado": self.ruta.exists(),
                "modelo_cargado": self.modelo is not None, "credenciales_earthdata": self.credenciales,
                "dispositivo": DISPOSITIVO}

    def _modelo(self):
        if self.modelo is None:
            if not self.ruta.exists():
                raise ErrorProceso(f"Falta el modelo entrenado: copia {self.ruta.name} en hidrosar-modelo/modelos/")
            self.modelo = ModeloUNet(self.ruta)
            logging.info("modelo cargado: %s (%s, umbral %.2f, %s)", self.ruta.name, self.modelo.encoder, self.modelo.umbral, DISPOSITIVO)
        return self.modelo

    def procesar(self, bbox, urls_lluvia, referencias):
        inicio = time.time()
        modelo = self._modelo()
        if not self.credenciales:
            raise ErrorProceso("Faltan las credenciales de NASA Earthdata (EARTHDATA_USER y EARTHDATA_PASSWORD en el .env)")
        g = grilla(bbox)
        dem, worldcover = dem_y_cobertura(bbox, g)
        hh, megabytes = geocodificar(urls_lluvia, bbox, dem, g)
        if np.isfinite(hh).mean() < COBERTURA_MINIMA:
            raise ErrorProceso("La pasada de lluvia cubre menos del 20 % del área")
        secos = []
        for urls in referencias:
            h, mb = geocodificar(urls, bbox, dem, g)
            megabytes += mb
            if np.isfinite(h).mean() >= COBERTURA_MINIMA:
                secos.append(h)
        mascara, metodo = agua_de_lluvia(modelo, hh, secos, worldcover)
        geometria, charcos, area = vectorizar(mascara, g, bbox)
        return {"geometria": geometria, "charcos": charcos, "area_m2": area, "mb_descargados": round(megabytes, 1),
                "metodo": metodo, "segundos": round(time.time() - inicio, 1)}
