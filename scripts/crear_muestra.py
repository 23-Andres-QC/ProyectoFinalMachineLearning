import os, glob, re, shutil, random
import numpy as np, rasterio

random.seed(42)
DESTINO = "muestra"

def copiar(origen):
    destino = os.path.join(DESTINO, origen)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.copy2(origen, destino)

def fraccion_agua(ruta, positivos, invalidos):
    with rasterio.open(ruta) as s:
        a = s.read(1)
    v = ~np.isin(a, invalidos)
    return np.isin(a, positivos)[v].mean() if v.any() else 0.0

def elegir(candidatos, n, frac, n_agua):
    random.shuffle(candidatos)
    con = [c for c in candidatos if frac(c) > 0.05][:n_agua]
    sin = [c for c in candidatos if c not in con][: n - len(con)]
    return con + sin

C = "sen1floods11_colombia/WeaklyLabeled"
ids = sorted(os.path.basename(f).replace("_S1Weak.tif", "") for f in glob.glob(f"{C}/S1Weak/*.tif"))
for i in elegir(ids, 12, lambda i: fraccion_agua(f"{C}/S1OtsuLabelWeak/{i}_S1OtsuLabelWeak.tif", [1], [-1]), 9):
    copiar(f"{C}/S1Weak/{i}_S1Weak.tif")
    copiar(f"{C}/S1OtsuLabelWeak/{i}_S1OtsuLabelWeak.tif")

N_KS = {"1111002": 6, "1111003": 6, "1111004": 16, "1111005": 6, "1111006": 6}
for act, n in N_KS.items():
    parches = [os.path.dirname(f) for f in glob.glob(f"kurosiwo/{act}/**/info.json", recursive=True)]
    parches = [p for p in parches if glob.glob(f"{p}/MK0_MLU_*.tif")]
    for p in elegir(parches[:400], n, lambda p: fraccion_agua(glob.glob(f"{p}/MK0_MLU_*.tif")[0], [1, 2], [3]), n * 2 // 3):
        for f in glob.glob(f"{p}/*"):
            copiar(f)

U = "urbansarfloods/urban_sar_floods"
por_evento = {}
for c in ["02_FO", "03_FU", "01_NF"]:
    for f in sorted(os.listdir(f"{U}/{c}/SAR")):
        ev = re.match(r"\d+_[A-Za-z]+", f).group()
        por_evento.setdefault(ev, {}).setdefault(c, []).append(f)
for ev, clases in sorted(por_evento.items()):
    elegidos = [(c, random.choice(clases[c])) for c in ["02_FO", "03_FU", "01_NF"] if c in clases][:2]
    for c, f in elegidos:
        copiar(f"{U}/{c}/SAR/{f}")
        copiar(f"{U}/{c}/GT/{f.replace('_SAR.tif', '_GT.tif')}")

n = sum(len(fs) for _, _, fs in os.walk(DESTINO))
mb = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(DESTINO) for f in fs) / 1e6
print(f"{n} archivos, {mb:.0f} MB en {DESTINO}/")
