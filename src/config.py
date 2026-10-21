"""Configuración central del pipeline: rutas, eventos, partición e hiperparámetros."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("PML_DATOS", RAIZ / "Data"))
SALIDA = Path(os.environ.get("PML_SALIDA", DATOS / "procesado"))
PREPARADO = SALIDA / "preparado"      # lo que produce preparacion_datos.ipynb (y lo único que lee el pipeline)
PRUEBAS = PREPARADO / "pruebas"       # Bolivia y Lima ya alineadas en su grilla, con capas auxiliares
RESULTADOS = SALIDA / "resultados"    # modelos, métricas y predicciones de pipeline_inundaciones.ipynb

# --- Fuente (Ruta A: entrenamiento / validación) ---
# Solo Kuro Siwo: su etiqueta sigue la imagen a nivel de píxel y trae manchas chicas. Se descartaron
# Sen1Floods11 Colombia (etiqueta Otsu), UrbanSARFloods (polígonos gruesos, sin agua permanente) y
# Kuro Siwo Madagascar (75-90 % del agua en ríos y cuerpos > 100 ha).
KUROSIWO = DATOS / "kurosiwo"
# --- Fuentes (Ruta B y comparación adicional) ---
BOLIVIA = DATOS / "sen1floods11_bolivia" / "HandLabeled"
LIMA = DATOS / "test_lima" / "procesadas"
EMSN038 = DATOS / "test_lima" / "emsn038_2017" / "EMSN038_UTM18S_v0.gdb"
HAND = sorted((DATOS / "test_lima" / "auxiliares" / "glo30_hand").glob("*.tif"))
JRC = sorted((DATOS / "test_lima" / "auxiliares" / "jrc_occurrence").glob("*.tif"))
DEM = sorted((DATOS / "test_lima" / "auxiliares" / "glo30_dem").glob("*.tif"))
# Teselas JRC Global Surface Water de los lugares de entrenamiento (las descarga preparacion_datos.ipynb).
JRC_GLOBAL = DATOS / "jrc_occurrence"
JRC_PERMANENTE = 80   # ocurrencia (%) desde la que un píxel se considera agua permanente

EVENTOS_KS = {1111002: "chad", 1111003: "yibuti", 1111004: "harvey"}
# Validación: bloques geográficos de Harvey (el único evento grande). Se elige ~VAL_FRAC de sus teselas
# por bloques de VAL_BLOQUE_KM km y se descartan las teselas de entrenamiento que tocan a una de validación.
VAL_EVENTO = "harvey"
VAL_FRAC = 0.2
VAL_BLOQUE_KM = 10

# Clases unificadas de las etiquetas guardadas en cada parche.
SIN_AGUA, AGUA_PERMANENTE, INUNDACION_ABIERTA, INUNDACION_URBANA = 0, 1, 2, 3

# Dos experimentos:
#   "agua"   -> 2 canales (VV, VH durante el evento), positivo = cualquier agua. Es la configuración del informe.
#   "cambio" -> 4 canales (VV, VH antes + VV, VH durante), positivo = inundación nueva.
#               Solo usa teselas con imagen previa.
# Qué eventos entran en cada modo lo decide la evaluación de calidad de preparacion_datos.ipynb.
MODOS = {
    "agua":   {"canales": [2, 3], "positivas": [1, 2, 3], "requiere_pre": False},
    "cambio": {"canales": [0, 1, 2, 3], "positivas": [2, 3], "requiere_pre": True},
}
NOMBRES_CANALES = ["VV_pre", "VH_pre", "VV_post", "VH_post"]

# --- Evaluación de calidad de las fuentes (¿sirven para entrenar detección de agua?) ---
# Cómo se hicieron las etiquetas de cada fuente: una etiqueta sacada con un umbral sobre la propia
# imagen SAR no le enseña al modelo nada que no sea ese umbral.
ORIGEN_ETIQUETAS = {"kurosiwo": "manual"}
CALIDAD = {
    "agua_permanente_min": 50,   # % del agua permanente JRC que la etiqueta marca como agua
    "agua_oscura_min": 50,       # % de píxeles etiquetados como agua con VH < VH_AGUA (agua visible en radar)
    "auc_dvh_min": 0.70,         # separación por ΔVH entre inundación y resto (solo modo cambio)
    "ventanas_min": 10,          # ventanas T×T válidas mínimas por evento (Yibuti, desértico como Lima, tiene 19)
}
VH_AGUA = -18.0
ITEMS_CALIDAD = 40               # items muestreados por evento para la evaluación

# --- Preparación ---
T = 256                   # lado del parche
DB_MIN, DB_MAX = -30.0, 5.0
DB_INVALIDO = -50.0       # por debajo es borde/sin dato (en Lima aparecen valores de -105 dB)
FRAC_VALIDA_MIN = 0.2
FRAC_AGUA_POSITIVO = 0.01
MAX_PARCHES_EVENTO = 4000  # tope por evento y partición (Harvey tiene ~5 000 teselas de 224×224)
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

# No se recorre el dataset completo: de cada evento que sirve se toman items al azar hasta tener
# unas VENTANAS_INVENTARIO ventanas, de las que luego se eligen MAX_PARCHES_EVENTO parches.
VENTANAS_INVENTARIO = 4 * MAX_PARCHES_EVENTO
