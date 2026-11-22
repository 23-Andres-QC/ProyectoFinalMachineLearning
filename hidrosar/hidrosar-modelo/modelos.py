"""Catálogo de los modelos que hay en /modelos y cómo corre cada uno.

En el selector se agrupan así:
- Deep Learning · Vol1: las U-Net de cambio del pipeline final y las U-Net de agua del notebook 01 (raíz de /modelos).
- Deep Learning · Vol2: las U-Net de agua de ModelosVol3 (carpeta vol3/).
- Machine Learning · Vol2: el ML por píxel de ModelosVol3 (carpeta vol3/, a 5 m).
Los id de vol3/ no cambian para que las evaluaciones guardadas sigan apuntando a su modelo.

Hay dos tipos:
- «agua»: marcan el agua en una imagen. El agua de lluvia sale de comparar la imagen de la lluvia con los días secos
  (segmentacion.agua_de_lluvia).
- «cambio»: U-Net de 2 canales del pipeline final (imagen de la lluvia e imagen seca previa). Marcan directamente el agua
  nueva (segmentacion.agua_nueva_por_cambio).
"""
import json
import logging
import os
import unicodedata
import warnings
from collections import OrderedDict
from pathlib import Path

import numpy as np
import segmentation_models_pytorch as smp
import torch
from scipy import ndimage

from errores import ErrorProceso
from segmentacion import DISPOSITIVO, ModeloUNet

CARPETA = Path(os.environ.get("MODELOS_DIR", "/modelos"))
VOL3 = "vol3"
FAMILIAS = {
    "vol1_dl": "Deep Learning · Vol1",
    "vol2_dl": "Deep Learning · Vol2",
    "vol2_ml": "Machine Learning · Vol2",
}
NOMBRES_VOL3 = {
    "unet_efficientnet-b0": "U-Net efficientnet-b0",
    "unet_mobilenet_v2": "U-Net mobilenet_v2",
    "unet_resnet34": "U-Net resnet34",
    "unet_resnet34_desde_cero": "U-Net resnet34 desde cero",
    "ml_adaboost": "AdaBoost",
    "ml_arbol_de_decision": "Árbol de decisión",
    "ml_histgradientboosting": "HistGradientBoosting",
    "ml_knn": "KNN",
    "ml_naive_bayes": "Naive Bayes",
    "ml_random_forest": "Random Forest",
    "ml_random_forest_optimizado": "Random Forest optimizado",
    "ml_random_forest_pendiente": "Random Forest + pendiente",
    "ml_red_neuronal_mlp": "Red neuronal MLP",
    "ml_regresion_logistica_base": "Regresión logística base",
    "ml_svm_rbf_8_000_pixeles": "SVM rbf de 8 000 píxeles",
    "ml_xgboost": "XGBoost",
}
LENTOS_VOL3 = {"ml_knn", "ml_svm_rbf_8_000_pixeles"}
DESCRIPCION = {
    "cambio": "Compara la imagen de la lluvia con el día seco previo de la misma órbita y marca el agua nueva. "
              "Necesita al menos un día seco de referencia.",
    "ensamble": "Promedia las 4 U-Net de cambio; fue el mejor modelo del pipeline final. Necesita al menos un día seco "
                "de referencia.",
    "unet": "Marca el agua en la imagen de la lluvia y se queda con la que no estaba en los días secos.",
    "vol3_unet": "U-Net de 1 canal del notebook 01 con el umbral que trae guardado. Marca el agua en la imagen "
                 "de la lluvia y se queda con la que no estaba en los días secos.",
    "vol3_ml": "Clasifica cada píxel a 5 m con la media y la desviación de HH en ventanas de 5×5 y 15×15 (notebook 01, "
               "sección 7) y el umbral elegido en validación. El agua de lluvia es la que no estaba en los días secos.",
}


def _descripcion_vol3(stem):
    if stem.startswith("unet_"):
        return DESCRIPCION["vol3_unet"]
    texto = DESCRIPCION["vol3_ml"]
    if stem == "ml_random_forest_pendiente":
        texto = texto.replace("15×15 (notebook 01", "15×15 más la pendiente del terreno (notebook 01")
    if stem in LENTOS_VOL3:
        texto += " Es lento en recortes grandes."
    return texto


def _sin_tildes(texto):
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode().lower()


def _umbrales():
    archivo = CARPETA / "umbrales.json"
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}


def catalogo():
    """Los modelos que hay en /modelos, en el orden en que se muestran."""
    lista = []
    cambio = sorted(CARPETA.glob("unet_cambio_*.pt"))
    if len(cambio) > 1:
        lista.append({"id": "unet_cambio_ensamble", "nombre": "Ensamble de U-Net de cambio", "familia": FAMILIAS["vol1_dl"],
                      "tipo": "cambio", "descripcion": DESCRIPCION["ensamble"]})
    for p in cambio:
        lista.append({"id": p.stem, "nombre": f"U-Net de cambio {p.stem.removeprefix('unet_cambio_')}",
                      "familia": FAMILIAS["vol1_dl"], "tipo": "cambio", "descripcion": DESCRIPCION["cambio"]})
    for p in sorted(CARPETA.glob("unet_*.pt")):
        if not p.stem.startswith("unet_cambio_"):
            lista.append({"id": p.stem, "nombre": f"U-Net {p.stem.removeprefix('unet_')}", "familia": FAMILIAS["vol1_dl"],
                          "tipo": "agua", "descripcion": DESCRIPCION["unet"]})
    vol3 = CARPETA / VOL3
    for familia, patron in (("vol2_dl", "unet_*.pt"), ("vol2_ml", "ml_*.joblib")):
        for p in sorted(vol3.glob(patron), key=lambda p: _sin_tildes(NOMBRES_VOL3.get(p.stem, p.stem))):
            # «(Vol2)» en el nombre para no confundirlos en Evaluaciones con las U-Net de Vol1 que se llaman igual
            lista.append({"id": f"{VOL3}/{p.stem}", "nombre": f"{NOMBRES_VOL3.get(p.stem, p.stem)} (Vol2)",
                          "familia": FAMILIAS[familia], "tipo": "agua", "descripcion": _descripcion_vol3(p.stem)})
    return lista


# --- U-Net de cambio (2 canales) ---

class UNetCambio:
    """Una o varias U-Net de 2 canales (evento y previa). Con varias, se promedian las probabilidades (ensamble)."""
    tipo = "cambio"

    def __init__(self, rutas, umbral):
        self.redes = []
        for ruta in rutas:
            guardado = torch.load(ruta, map_location="cpu", weights_only=True)
            red = smp.Unet(guardado["encoder"], encoder_weights=None, in_channels=2, classes=1)
            red.load_state_dict(guardado["pesos"])
            media = np.asarray(guardado["media"], "float32")[:, None, None]
            desv = np.asarray(guardado["desv"], "float32")[:, None, None]
            self.redes.append((red.to(DISPOSITIVO).eval(), media, desv))
        self.umbral = float(umbral)

    def _mapa(self, red, x2, lote=16):
        """Ventanas de 256 con paso de 128 y promedio simple en los solapes (`mapa` del pipeline final)."""
        _, alto0, ancho0 = x2.shape
        alto, ancho = max(alto0, 256), max(ancho0, 256)
        x2 = np.pad(x2, ((0, 0), (0, alto - alto0), (0, ancho - ancho0)))
        filas = sorted(set(range(0, alto - 255, 128)) | {alto - 256})
        columnas = sorted(set(range(0, ancho - 255, 128)) | {ancho - 256})
        posiciones = [(i, j) for i in filas for j in columnas]
        suma, cuenta = np.zeros((alto, ancho), "float32"), np.zeros((alto, ancho), "float32")
        with torch.no_grad():
            for k in range(0, len(posiciones), lote):
                grupo = posiciones[k:k + lote]
                t = torch.from_numpy(np.stack([x2[:, i:i + 256, j:j + 256] for i, j in grupo])).to(DISPOSITIVO)
                prob = torch.sigmoid(red(t)).float().cpu().numpy()[:, 0]
                for (i, j), q in zip(grupo, prob):
                    suma[i:i + 256, j:j + 256] += q
                    cuenta[i:i + 256, j:j + 256] += 1
        return (suma / np.maximum(cuenta, 1))[:alto0, :ancho0]

    def probabilidad(self, x2):
        mapas = []
        for red, media, desv in self.redes:
            xn = np.nan_to_num((np.clip(x2, -35, 10) - media) / desv).astype("float32")
            mapas.append(self._mapa(red, xn))
        prob = np.mean(mapas, 0)
        return np.where(np.isfinite(x2).all(0), prob, np.nan)


# --- Machine Learning por píxel del notebook 01 (Vol2 = carpeta vol3/, a 5 m) ---

class AguaPixelML:
    """Cada .joblib trae {"modelo", "columnas", "umbral"}. Las variables salen de HH suavizado 5×5 (la entrada de la
    U-Net), como en las secciones 7 y 8.2 del notebook 01; la pendiente se calcula del DEM suavizado 7×7."""
    tipo = "agua"
    LOTE = 500_000

    def __init__(self, ruta):
        import joblib
        guardado = joblib.load(ruta)
        self.modelo = guardado["modelo"]
        self.columnas = list(guardado["columnas"])
        self.umbral = float(guardado["umbral"])

    def _capas(self, s, dem):
        x = np.where(np.isfinite(s), s, np.nanmedian(s)).astype("float32")
        m5, m15 = ndimage.uniform_filter(x, 5), ndimage.uniform_filter(x, 15)
        capas = {
            "hh": lambda: x,
            "hh_media15": lambda: m15,
            "hh_desv5": lambda: np.sqrt(np.maximum(ndimage.uniform_filter(x ** 2, 5) - m5 ** 2, 0)),
            "hh_desv15": lambda: np.sqrt(np.maximum(ndimage.uniform_filter(x ** 2, 15) - m15 ** 2, 0)),
            "contraste15": lambda: x - m15,
            "pendiente": lambda: self._pendiente(dem),
        }
        faltan = [c for c in self.columnas if c not in capas]
        if faltan:
            raise ErrorProceso(f"El modelo pide variables que HidroSAR no calcula: {', '.join(faltan)}")
        return [capas[c]() for c in self.columnas]

    @staticmethod
    def _pendiente(dem):
        dem = np.where(np.isfinite(dem), dem, np.nanmedian(dem)).astype("float32")
        dy, dx = np.gradient(ndimage.uniform_filter(dem, 7), 5)
        return np.degrees(np.arctan(np.hypot(dx, dy)))

    def agua(self, hh, s, dem):
        valido = np.isfinite(s)
        agua = np.zeros(s.shape, bool)
        if not valido.any():
            return agua
        x = np.stack([c[valido] for c in self._capas(s, dem)], axis=1)
        with warnings.catch_warnings():
            # se entrenaron con tablas de pandas; aquí llegan como arreglos con las columnas en el mismo orden
            warnings.filterwarnings("ignore", message="X does not have valid feature names")
            prob = np.concatenate([self.modelo.predict_proba(x[k:k + self.LOTE])[:, 1]
                                   for k in range(0, len(x), self.LOTE)])
        agua[valido] = prob >= self.umbral
        return agua


# --- Carga con caché ---

class Modelos:
    """Carga los modelos cuando se piden y guarda en memoria los últimos usados."""

    def __init__(self, predeterminado, maximo=3):
        self.predeterminado = predeterminado
        self.maximo = maximo
        self.cargados = OrderedDict()

    def info(self, id_):
        id_ = id_ or self.predeterminado
        info = next((m for m in catalogo() if m["id"] == id_), None)
        if info is None:
            raise ErrorProceso(f"El modelo «{id_}» no está en hidrosar-modelo/modelos/")
        return info

    def obtener(self, id_):
        info = self.info(id_)
        if info["id"] in self.cargados:
            self.cargados.move_to_end(info["id"])
            return info, self.cargados[info["id"]]
        modelo = self._cargar(info["id"])
        self.cargados[info["id"]] = modelo
        while len(self.cargados) > self.maximo:
            self.cargados.popitem(last=False)
        logging.info("modelo cargado: %s (%s)", info["nombre"], DISPOSITIVO)
        return info, modelo

    def _cargar(self, id_):
        if id_.startswith("unet_cambio_"):
            umbrales = _umbrales()
            if id_ == "unet_cambio_ensamble":
                rutas, clave = sorted(CARPETA.glob("unet_cambio_*.pt")), "U-Net cambio ensamble"
            else:
                rutas, clave = [CARPETA / f"{id_}.pt"], f"U-Net cambio {id_.removeprefix('unet_cambio_')}"
            if clave not in umbrales:
                raise ErrorProceso(f"Falta el umbral de «{clave}» en hidrosar-modelo/modelos/umbrales.json")
            return UNetCambio(rutas, umbrales[clave])
        if id_.startswith(f"{VOL3}/ml_"):
            return AguaPixelML(CARPETA / f"{id_}.joblib")
        return ModeloUNet(CARPETA / f"{id_}.pt")
