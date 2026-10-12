"""Configuración central del pipeline: rutas, eventos, partición e hiperparámetros."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("PML_DATOS", RAIZ / "Data"))
SALIDA = Path(os.environ.get("PML_SALIDA", DATOS / "procesado"))

# --- Fuentes (Ruta A: entrenamiento / validación) ---
COLOMBIA = DATOS / "sen1floods11_colombia" / "WeaklyLabeled"
KUROSIWO = DATOS / "kurosiwo"
URBANSAR = DATOS / "urbansarfloods" / "urban_sar_floods"
# --- Fuentes (Ruta B y comparación adicional) ---
BOLIVIA = DATOS / "sen1floods11_bolivia" / "HandLabeled"
LIMA = DATOS / "test_lima" / "procesadas"
EMSN038 = DATOS / "test_lima" / "emsn038_2017" / "EMSN038_UTM18S_v0.gdb"
HAND = sorted((DATOS / "test_lima" / "auxiliares" / "glo30_hand").glob("*.tif"))
JRC = sorted((DATOS / "test_lima" / "auxiliares" / "jrc_occurrence").glob("*.tif"))

EVENTOS_KS = {1111002: "chad", 1111003: "yibuti", 1111004: "harvey",
              1111005: "madagascar_1", 1111006: "madagascar_2"}
EVENTOS_VAL = {"madagascar_1", "madagascar_2", "20210319_PortMacquarie",
               "20210324_Sydney", "20220302_Coraki", "20220705_Sydney"}

# Clases unificadas de las etiquetas guardadas en cada parche.
SIN_AGUA, AGUA_PERMANENTE, INUNDACION_ABIERTA, INUNDACION_URBANA = 0, 1, 2, 3

# Dos experimentos:
#   "agua"   -> 2 canales (VV, VH durante el evento), positivo = cualquier agua. Es la configuración del informe.
#   "cambio" -> 4 canales (VV, VH antes + VV, VH durante), positivo = inundación nueva.
#               Solo usa fuentes con imagen previa (Kuro Siwo y UrbanSARFloods).
# "excluir": Colombia sale del modo agua porque sus etiquetas (Otsu sobre VH) enseñan "oscuro = agua"
#            y aumentan los falsos positivos en el desierto de Lima (ver scripts/evaluar_datos.py).
MODOS = {
    "agua":   {"canales": [2, 3], "positivas": [1, 2, 3], "requiere_pre": False, "excluir": ["colombia"]},
    "cambio": {"canales": [0, 1, 2, 3], "positivas": [2, 3], "requiere_pre": True, "excluir": []},
}
NOMBRES_CANALES = ["VV_pre", "VH_pre", "VV_post", "VH_post"]

# --- Preparación ---
T = 256                   # lado del parche
DB_MIN, DB_MAX = -30.0, 5.0
DB_INVALIDO = -50.0       # por debajo es borde/sin dato (en Lima aparecen valores de -105 dB)
FRAC_VALIDA_MIN = 0.2
FRAC_AGUA_POSITIVO = 0.01
MAX_PARCHES_EVENTO = 800  # tope por evento para que Harvey y UrbanSAR no dominen
FRAC_CON_AGUA = 0.6       # proporción objetivo de parches con agua dentro del tope
SEMILLA = 42

# --- Entrenamiento ---
ENCODERS = ["resnet34", "vgg19", "efficientnet-b0", "mobilenet_v2"]
MAX_EPOCAS = 10   # la evaluación mostró que el mejor IoU de validación llega en las épocas 1-3
PACIENCIA = 3
LOTE = 16
LR = 1e-4
NUM_WORKERS = 2   # cada proceso auxiliar carga torch (~0.6 GB de RAM en Windows)
UMBRAL = 0.5

# --- Inferencia sobre escenas ---
PASO = 128
HAND_MAX = 10

# --- Modo rápido (PML_RAPIDO=1): prueba de humo del pipeline completo en minutos ---
MAX_ITEMS_EVENTO = None
if os.environ.get("PML_RAPIDO") == "1":
    MAX_ITEMS_EVENTO, MAX_PARCHES_EVENTO = 6, 12
    ENCODERS, MAX_EPOCAS, NUM_WORKERS = ["mobilenet_v2"], 1, 0
