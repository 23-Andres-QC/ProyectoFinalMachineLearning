"""Avance de cada evaluación: qué pasos van hechos, cuál está en curso y cuánto se ha descargado.

El backend lo pide cada pocos segundos (GET /progreso/{id}) mientras espera el resultado y lo guarda en la base, así el
panel muestra en qué va: carga del modelo, relieve, descarga de la lluvia y de cada día seco, segmentación y polígonos.
"""
import threading
import time
from collections import OrderedDict

_candado = threading.Lock()
_avances = OrderedDict()
MAXIMO = 50  # se recuerdan las últimas evaluaciones, también las que fallaron


def mb(valor):
    return f"{valor:.1f} MB" if valor < 10 else f"{valor:.0f} MB"


class Avance:
    """Sin id no se registra (por ejemplo, en las pruebas): solo se lleva la cuenta."""

    def __init__(self, id_=None):
        self.pasos = []
        if id_ is not None:
            with _candado:
                _avances[id_] = self
                _avances.move_to_end(id_)
                while len(_avances) > MAXIMO:
                    _avances.popitem(last=False)

    def planear(self, pasos):
        with _candado:
            self.pasos = [{"clave": c, "texto": t, "estado": "pendiente", "detalle": "", "inicio": None, "fin": None}
                          for c, t in pasos]

    def agregar(self, clave, texto, antes_de):
        """Un paso que no estaba previsto (por ejemplo, un día seco de respaldo), justo antes del paso `antes_de`."""
        with _candado:
            i = next(k for k, p in enumerate(self.pasos) if p["clave"] == antes_de)
            self.pasos.insert(i, {"clave": clave, "texto": texto, "estado": "pendiente", "detalle": "", "inicio": None,
                                  "fin": None})

    def _paso(self, clave):
        return next(p for p in self.pasos if p["clave"] == clave)

    def empezar(self, clave, detalle=""):
        with _candado:
            self._paso(clave).update(estado="en_curso", detalle=detalle, inicio=time.time())

    def detallar(self, clave, detalle):
        with _candado:
            self._paso(clave)["detalle"] = detalle

    def terminar(self, clave, detalle=None):
        with _candado:
            p = self._paso(clave)
            p.update(estado="hecho", fin=time.time())
            if detalle is not None:
                p["detalle"] = detalle

    def fallar(self):
        """El paso que estaba en curso queda marcado con error: así se ve dónde se detuvo."""
        with _candado:
            for p in self.pasos:
                if p["estado"] == "en_curso":
                    p.update(estado="error", fin=time.time())

    def foto(self):
        ahora = time.time()
        with _candado:
            return {"pasos": [{"clave": p["clave"], "texto": p["texto"], "estado": p["estado"], "detalle": p["detalle"],
                               "segundos": round((p["fin"] or ahora) - p["inicio"]) if p["inicio"] else None}
                              for p in self.pasos]}


def avance_de(id_):
    with _candado:
        avance = _avances.get(id_)
    return avance.foto() if avance else None
