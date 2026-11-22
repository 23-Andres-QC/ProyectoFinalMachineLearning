import os
import re
import time
from pathlib import Path

import numpy as np

from errores import ErrorProceso
from modelos import Modelos, catalogo
from nisar import geocodificar, preparar_credenciales
from progreso import Avance, mb
from segmentacion import DISPOSITIVO, agua_de_lluvia, agua_nueva_por_cambio, vectorizar
from terreno import dem_y_cobertura, grilla

SIN_DATOS = 0.01         # con menos del 1 % del área con radar no hay nada que segmentar
COBERTURA_AVISO = 0.9    # por debajo se avisa qué parte del área se segmentó
REFERENCIA_MINIMA = 0.2  # un día seco sirve si tiene datos en al menos el 20 % de lo que cubre la pasada de lluvia


def fecha_de(urls):
    """Fecha AAAAMMDD de la toma, sacada del nombre del archivo RSLC (…_20261105T105845_…)."""
    m = re.search(r"_(\d{8})T\d{6}_", Path(urls[0]).name)
    return m.group(1) if m else ""


def fecha_corta(urls):
    """« (17/11/2026)» para los textos del avance; vacío si el nombre del archivo no trae la fecha."""
    f = fecha_de(urls)
    return f" ({f[6:]}/{f[4:6]}/{f[:4]})" if f else ""


def texto_comparacion(secos):
    if not secos:
        return "sin día seco de referencia"
    f = secos[0][0]
    return f"comparada con el día seco del {f[6:]}/{f[4:6]}/{f[:4]}" if f else "comparada con el día seco"


class Procesador:
    def __init__(self):
        # MODELO_PT es el modelo que se usa cuando no se elige ninguno
        self.predeterminado = Path(os.environ.get("MODELO_PT", "/modelos/unet_resnet34.pt")).stem
        self.modelos = Modelos(self.predeterminado)
        self.credenciales = preparar_credenciales()

    def estado(self):
        lista = catalogo()
        return {"disponible": True, "modelo": self.predeterminado,
                "modelo_encontrado": any(m["id"] == self.predeterminado for m in lista),
                "modelos": lista, "predeterminado": self.predeterminado, "credenciales_earthdata": self.credenciales, "dispositivo": DISPOSITIVO}

    def procesar(self, bbox, urls_lluvia, referencias, modelo_id="", avance=None):
        """Cada paso se informa en `avance` (progreso.Avance) para que el panel muestre en qué va."""
        inicio = time.time()
        avance = avance or Avance()
        info = self.modelos.info(modelo_id)
        if info["tipo"] == "cambio" and not referencias:
            raise ErrorProceso(f"El modelo «{info['nombre']}» compara la lluvia con un día seco previo de la misma órbita y "
                               "esta pasada no tiene días secos de referencia. Elige otro modelo o una pasada con días secos.")
        if not self.credenciales:
            raise ErrorProceso("Faltan las credenciales de NASA Earthdata (EARTHDATA_USER y EARTHDATA_PASSWORD en el .env)")
        avance.planear([
            ("modelo", f"Carga del modelo {info['nombre']}"),
            ("terreno", "Relieve (DEM) y cobertura del suelo del área"),
            ("lluvia", f"Descarga del recorte de la pasada de lluvia{fecha_corta(urls_lluvia)}"),
            *([("seco0", f"Descarga del día seco de referencia{fecha_corta(referencias[0])}")] if referencias else []),
            ("segmentacion", "Segmentación del agua con el modelo"),
            ("poligonos", "Polígonos del agua y de los charcos"),
        ])

        avance.empezar("modelo")
        info, modelo = self.modelos.obtener(modelo_id)
        avance.terminar("modelo")

        avance.empezar("terreno")
        g = grilla(bbox)
        dem, worldcover = dem_y_cobertura(bbox, g)
        avance.terminar("terreno", f"grilla de 5 m de {g['width']} × {g['height']} píxeles")

        avance.empezar("lluvia", "conectando con NISAR…")
        hh, megabytes = geocodificar(urls_lluvia, bbox, dem, g, lambda v: avance.detallar("lluvia", mb(v)))
        cubierto = np.isfinite(hh)
        cobertura = float(cubierto.mean())
        if cobertura < SIN_DATOS:
            avance.detallar("lluvia", f"{mb(megabytes)} · sin datos del radar en el área")
            raise ErrorProceso("La pasada de lluvia no tiene datos del radar en esta área: queda fuera de la franja que tomó "
                               "NISAR. Mueve el rectángulo hacia la zona que sí cubre o elige otra pasada.")
        avance.terminar("lluvia", f"{mb(megabytes)} · datos en el {max(1, round(cobertura * 100))} % del área")

        # Un solo día seco: el primero de la lista, que es el más reciente antes de la lluvia. Los siguientes (evaluaciones
        # guardadas con dos) solo se bajan si ese no tiene datos donde está la pasada de lluvia.
        secos = []
        for i, urls in enumerate(referencias):
            clave = f"seco{i}"
            if i:
                avance.agregar(clave, f"Descarga de un día seco de respaldo{fecha_corta(urls)}", antes_de="segmentacion")
            avance.empezar(clave, "conectando con NISAR…")
            h, bajado = geocodificar(urls, bbox, dem, g, lambda v, c=clave: avance.detallar(c, mb(v)))
            megabytes += bajado
            if np.isfinite(h)[cubierto].mean() >= REFERENCIA_MINIMA:
                secos.append((fecha_de(urls), h))
                avance.terminar(clave, mb(bajado))
                break
            avance.terminar(clave, f"{mb(bajado)} · no tiene datos donde está la lluvia: no se usa")

        avance.empezar("segmentacion", info["nombre"])
        if info["tipo"] == "cambio":
            if not secos:
                raise ErrorProceso("El día seco de referencia no tiene datos donde está la pasada de lluvia: el modelo de "
                                   "cambio no tiene con qué comparar. Elige otro modelo.")
            # los modelos de cambio marcan solo el agua nueva: no hay una capa de toda el agua de ese día
            mascara, metodo = agua_nueva_por_cambio(modelo, hh, secos, fecha_de(urls_lluvia), worldcover, dem)
            segmentada = None
        else:
            mascara, metodo, segmentada = agua_de_lluvia(modelo, hh, [h for _, h in secos], worldcover, dem)
        avance.terminar("segmentacion", f"{info['nombre']} · {texto_comparacion(secos)}")

        avance.empezar("poligonos")
        agua_geo = agua_m2 = None
        if segmentada is not None:
            agua_geo, _, agua_m2 = vectorizar(segmentada, g, bbox)
        geometria, charcos, area = vectorizar(mascara, g, bbox)
        avance.terminar("poligonos", "1 charco" if charcos == 1 else f"{charcos} charcos")
        aviso = ""
        if cobertura < COBERTURA_AVISO:
            aviso = (f"La pasada solo tiene datos del radar en el {max(1, round(cobertura * 100))} % del área: se segmentó "
                     "esa parte y el resto queda sin evaluar.")
        return {"geometria": geometria, "charcos": charcos, "area_m2": area, "agua": agua_geo, "agua_m2": agua_m2,
                "mb_descargados": round(megabytes, 1),
                "metodo": metodo, "modelo": info["id"], "cobertura_pct": round(cobertura * 100, 1), "aviso": aviso,
                "segundos": round(time.time() - inicio, 1)}
