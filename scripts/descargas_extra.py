"""Descargas pendientes de la metodología: Sen1Floods11 Bolivia y rásters auxiliares de Lima."""
import os, time, requests

def bajar(url, destino):
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    for intento in range(1, 11):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                size = int(r.headers.get("Content-Length", 0))
                if os.path.exists(destino) and os.path.getsize(destino) == size:
                    return "ya estaba"
                with open(destino, "wb") as f:
                    for trozo in r.iter_content(1024 * 1024):
                        f.write(trozo)
            return "OK"
        except requests.exceptions.RequestException as e:
            print(f"  se cortó {os.path.basename(destino)} ({type(e).__name__}), reintento {intento}", flush=True)
            time.sleep(10)
    return "FALLÓ"

# ---------- 1) Rásters auxiliares para Lima (pasos 2 y 3) ----------
AUX = "test_lima/auxiliares"
TILES = ["S13_00_W078_00", "S12_00_W078_00", "S13_00_W077_00", "S12_00_W077_00"]
aux = {f"{AUX}/jrc_occurrence/occurrence_80W_10Sv1_4_2021.tif":
       "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_80W_10Sv1_4_2021.tif"}
for t in TILES:
    aux[f"{AUX}/glo30_hand/Copernicus_DSM_COG_10_{t}_HAND.tif"] = \
        f"https://glo-30-hand.s3.amazonaws.com/v1/2021/Copernicus_DSM_COG_10_{t}_HAND.tif"
    aux[f"{AUX}/glo30_dem/Copernicus_DSM_COG_10_{t}_DEM.tif"] = \
        f"https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{t}_DEM/Copernicus_DSM_COG_10_{t}_DEM.tif"
for destino, url in aux.items():
    print(f"[aux] {bajar(url, destino)} {destino}", flush=True)

# ---------- 2) Sen1Floods11 Bolivia (test oficial del paper) ----------
BUCKET, BASE, PAIS = "sen1floods11", "v1.1/data/flood_events", "Bolivia"
DEST = f"sen1floods11_{PAIS.lower()}"
CAPAS = {"HandLabeled":   ["S1Hand", "LabelHand", "S1OtsuLabelHand", "JRCWaterHand"],
         "WeaklyLabeled": ["S1Weak", "S1OtsuLabelWeak"]}

def listar(prefijo):
    url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o"
    params, items = {"prefix": prefijo, "fields": "items(name,size),nextPageToken"}, []
    while True:
        data = requests.get(url, params=params, timeout=60).json()
        items += [(it["name"], int(it["size"])) for it in data.get("items", [])]
        if "nextPageToken" not in data:
            return items
        params["pageToken"] = data["nextPageToken"]

plan = [(g, c, n, s) for g, cs in CAPAS.items() for c in cs for n, s in listar(f"{BASE}/{g}/{c}/{PAIS}_")]
print(f"[bolivia] {len(plan)} archivos, {sum(s for *_, s in plan)/1e6:.1f} MB", flush=True)
mal = 0
for i, (g, c, n, s) in enumerate(plan, 1):
    destino = os.path.join(DEST, g, c, os.path.basename(n))
    if not (os.path.exists(destino) and os.path.getsize(destino) == s):
        bajar(f"https://storage.googleapis.com/{BUCKET}/{n}", destino)
    mal += os.path.getsize(destino) != s
    if i % 100 == 0:
        print(f"[bolivia] {i}/{len(plan)}", flush=True)
print(f"[bolivia] terminado, {mal} archivos con tamaño incorrecto", flush=True)
print("FIN", flush=True)
