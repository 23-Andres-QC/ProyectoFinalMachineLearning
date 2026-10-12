"""Evaluación de los datos de entrenamiento: ¿sirven para Lima y aporta usar más datos?

Etapas (cada una guarda su resultado en Data/procesado/evaluacion/ y se salta si ya existe):
  1. Inventario de ventanas (se comparte con el notebook principal).
  2. Radiometría por evento: separabilidad agua/no agua, "tierra oscura" y similitud con Lima.
  3. Extracción de parches y normalización (se comparten con el notebook principal).
  4. Experimentos con U-Net MobileNetV2 y presupuesto fijo de pasos:
       - curva de aprendizaje (10, 25, 50 y 100 % de los parches de train, por evento)
       - ablación: entrenar sin cada dataset
     Cada modelo se mide en validación (por fuente), Bolivia y Lima (2017 y 2023).

Uso:  python scripts/evaluar_datos.py
"""
import sys, json, time, glob, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np, pandas as pd, torch, rasterio, geopandas as gpd
from torch.utils.data import DataLoader

from src import config as C, datos as D, entrenamiento as E, inferencia as I

EV = C.SALIDA / "evaluacion"
EV.mkdir(parents=True, exist_ok=True)
DISP = "cuda" if torch.cuda.is_available() else "cpu"
ENCODER = "mobilenet_v2"
EPOCAS = 6                      # cada "época" = pasos de una época completa al 100 %
FRACCIONES = [0.1, 0.25, 0.5, 1.0]
BINS = np.arange(-30, 5.01, 0.5)
if C.MAX_ITEMS_EVENTO:  # modo rápido
    EPOCAS, FRACCIONES = 1, [0.5, 1.0]


def log(*a):
    texto = " ".join(str(x) for x in a)
    print(texto, flush=True)
    with open(EV / "evaluacion.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + texto + "\n")


def auc(pos, neg):
    """P(score_pos > score_neg) por histogramas (scores ya orientados)."""
    if len(pos) == 0 or len(neg) == 0:
        return np.nan
    b = np.linspace(min(pos.min(), neg.min()), max(pos.max(), neg.max()) + 1e-6, 513)
    hp, _ = np.histogram(pos, b); hn, _ = np.histogram(neg, b)
    hp, hn = hp / hp.sum(), hn / hn.sum()
    return float((hp * (np.cumsum(hn) - hn / 2)).sum())


def hist(x):
    h, _ = np.histogram(np.clip(x, -30, 5), BINS)
    return h / max(h.sum(), 1)


# ------------------------------------------------------------------ 1. inventario
def etapa_inventario(items):
    ruta_inv = C.SALIDA / "inventario.csv"
    if ruta_inv.exists():
        inv = pd.read_csv(ruta_inv)
    else:
        log("1. inventario de", len(items), "items")
        inv = D.inventario(items)
        inv.to_csv(ruta_inv, index=False)
    tabla = (inv.groupby(["particion", "dataset", "evento"])
             .agg(items=("item", "nunique"), ventanas=("i", "size"),
                  ventanas_con_agua=("frac_agua", lambda x: (x > C.FRAC_AGUA_POSITIVO).sum()),
                  agua_media=("frac_agua", "mean"), con_pre=("tiene_pre", "mean")).reset_index())
    tabla.to_csv(EV / "1_inventario_por_evento.csv", index=False)
    log("1. inventario listo:", len(inv), "ventanas")
    return inv


# ------------------------------------------------------------------ 2. radiometría
def lima_tierra():
    """VH de tierra (DEM > 1 m) en Lima 2017 y Lima Sur 2023, y si es oscura en ambas fechas."""
    dem_rutas = sorted((C.DATOS / "test_lima" / "auxiliares" / "glo30_dem").glob("*.tif"))
    out = {}
    for nombre, post, pre in [("Lima 2017", "lima_2017_0317", "lima_2017_0305"), ("Lima Sur 2023", "lima_2023_0316", "lima_2023_0304")]:
        x, perfil = I.leer_escena(C.LIMA / f"{post}.tif")
        p = I.leer_en_grilla(C.LIMA / f"{pre}.tif", perfil)
        dem = I.a_grilla(dem_rutas, perfil)
        m = D.validos_db(x) & D.validos_db(p) & (dem > 1)
        vh, vhp = x[1][m], p[1][m]
        out[nombre] = dict(vh=vh[::7], oscuro=float((vh < -20).mean()), oscuro_ambas=float(((vh < -20) & (vhp < -20)).mean()),
                           vh_mediana=float(np.median(vh)), dvh_p90abs=float(np.percentile(np.abs(vh - vhp), 90)))
        del x, p, dem, m
    return out


def etapa_radiometria(items):
    ruta_rad = EV / "2_radiometria_por_evento.csv"
    if not ruta_rad.exists():
        log("2. radiometría")
        lima = lima_tierra()
        h_lima = hist(lima["Lima Sur 2023"]["vh"])
        filas = []
        for (ds, ev), g in items.groupby(["dataset", "evento"]):
            g = g.sample(min(len(g), 40), random_state=C.SEMILLA)
            vh_a, vh_n, vhp_n, dvh_f, dvh_o = [], [], [], [], []
            for it in g.itertuples():
                pre, post, lab, val, val_pre = D.leer_item(ds, it.item)
                vh = post[1]
                vh_a.append(vh[val & (lab > 0)]); vh_n.append(vh[val & (lab == 0)])
                if pre is not None:
                    mp = val & val_pre
                    vhp_n.append(np.stack([vh[mp & (lab == 0)], pre[1][mp & (lab == 0)]]))
                    d = vh - pre[1]
                    dvh_f.append(d[mp & (lab >= 2)]); dvh_o.append(d[mp & (lab < 2)])
            a, n = np.concatenate(vh_a), np.concatenate(vh_n)
            fila = dict(dataset=ds, evento=ev, items_muestreados=len(g), pix_agua=len(a), pix_no_agua=len(n),
                        vh_mediana_agua=np.median(a) if len(a) else np.nan, vh_mediana_no_agua=np.median(n),
                        auc_vh_agua=auc(-a, -n),
                        tierra_oscura_pct=100 * (n < -20).mean(),
                        similitud_lima_sur=float(np.minimum(hist(n), h_lima).sum()))
            if vhp_n:
                vp = np.concatenate(vhp_n, axis=1)
                f, o = np.concatenate(dvh_f), np.concatenate(dvh_o)
                fila.update(tierra_oscura_ambas_pct=100 * ((vp[0] < -20) & (vp[1] < -20)).mean(),
                            dvh_mediana_inundacion=np.median(f) if len(f) else np.nan, dvh_mediana_resto=np.median(o),
                            auc_dvh_inundacion=auc(-f, -o))
            filas.append(fila)
            log(f"   {ds}/{ev}: AUC VH {fila['auc_vh_agua']:.3f} · tierra oscura {fila['tierra_oscura_pct']:.1f} %")
        rad = pd.DataFrame(filas)
        for nombre, v in lima.items():
            rad = pd.concat([rad, pd.DataFrame([dict(dataset="lima", evento=nombre, vh_mediana_no_agua=v["vh_mediana"],
                                                     tierra_oscura_pct=100 * v["oscuro"], tierra_oscura_ambas_pct=100 * v["oscuro_ambas"],
                                                     similitud_lima_sur=float(np.minimum(hist(v["vh"]), h_lima).sum()))])])
        rad.to_csv(ruta_rad, index=False)
    log("2. radiometría lista")


# ------------------------------------------------------------------ 3. parches
def etapa_parches(inv):
    ruta_idx, ruta_stats = C.SALIDA / "indice.csv", C.SALIDA / "stats.json"
    if not ruta_idx.exists():
        log("3. extracción de parches")
        indice = D.extraer_parches(D.muestrear(inv))
        indice.to_csv(ruta_idx, index=False)
    indice = pd.read_csv(ruta_idx)
    if not ruta_stats.exists():
        json.dump(D.estadisticas(indice), open(ruta_stats, "w"), indent=2)
    stats = json.load(open(ruta_stats))
    log("3. parches listos:", len(indice))
    return indice, stats


# ------------------------------------------------------------------ 4. experimentos
class PasosFijos(E.LotesBalanceados):
    def __init__(self, positivos, n_total, lote, pasos):
        super().__init__(positivos, n_total, lote)
        self.pasos = pasos

    def __len__(self):
        return self.pasos


def preparar_lima(stats):
    """Entradas normalizadas de Lima guardadas en disco (memmap) para no saturar la RAM."""
    cache = EV / "cache"
    cache.mkdir(exist_ok=True)
    if not (cache / "meta.json").exists():
        meta = {}
        gdb = C.EMSN038
        agua_ems = pd.concat([gpd.read_file(gdb, layer=c) for c in ["Potential_Maximum_flood", "Riverbank"]])
        zona = gpd.read_file(gdb, layer="EMSN038_AOI").overlay(gpd.read_file(gdb, layer="Footprints"), how="intersection")
        dem_rutas = sorted((C.DATOS / "test_lima" / "auxiliares" / "glo30_dem").glob("*.tif"))
        for clave, post, pre in [("l17", "lima_2017_0317", "lima_2017_0305"), ("l23", "lima_2023_0316", "lima_2023_0304")]:
            x, perfil = I.leer_escena(C.LIMA / f"{post}.tif")
            p = I.leer_en_grilla(C.LIMA / f"{pre}.tif", perfil)
            v = D.validos_db(x) & D.validos_db(p)
            capas = [p[0], p[1], x[0], x[1]]
            for modo, cfg in C.MODOS.items():
                out = np.lib.format.open_memmap(cache / f"{clave}_{modo}.npy", "w+", "float32", (len(cfg["canales"]),) + v.shape)
                for k, c in enumerate(cfg["canales"]):
                    out[k] = E.normalizar(capas[c][None], v, stats, [c])[0]
                out.flush(); del out
            tierra = (I.a_grilla(dem_rutas, perfil) > 1) & v
            np.save(cache / f"{clave}_tierra.npy", tierra)
            np.save(cache / f"{clave}_oscuro_ambas.npy", (x[1] < -20) & (p[1] < -20) & tierra)
            np.save(cache / f"{clave}_hand.npy", I.a_grilla(C.HAND, perfil) < C.HAND_MAX)
            if clave == "l17":
                ref = I.rasterizar(agua_ems, perfil).astype("int8")
                ref[I.rasterizar(zona, perfil) == 0] = -1
                ref[~v] = -1
                np.save(cache / "l17_ref.npy", ref)
                meta["otsu_17"] = float(I.otsu(x[1][ref != -1]))
                np.save(cache / "l17_otsu.npy", x[1] < meta["otsu_17"])
            del x, p, v
        json.dump(meta, open(cache / "meta.json", "w"))
    return cache


def evaluar_val_por_fuente(modelo, modo, val, stats):
    ds = E.Parches(val, modo, stats, aumentar=False)
    dl = DataLoader(ds, batch_size=C.LOTE, shuffle=False, num_workers=C.NUM_WORKERS)
    c = {k: np.zeros(4) for k in val.dataset.unique()}
    modelo.eval()
    k0 = 0
    with torch.no_grad(), torch.autocast(DISP, enabled=DISP == "cuda"):
        for x, y, m in dl:
            p = (torch.sigmoid(modelo(x.to(DISP)).float()) >= C.UMBRAL).cpu()
            y, m = y > 0.5, m > 0.5
            for b in range(len(x)):
                fuente = val.dataset.iloc[k0 + b]
                pb, yb, mb = p[b], y[b], m[b]
                c[fuente] += [(pb & yb & mb).sum().item(), (pb & ~yb & mb).sum().item(),
                              (~pb & yb & mb).sum().item(), (~pb & ~yb & mb).sum().item()]
            k0 += len(x)
    total = sum(c.values())
    return {"val_IoU": E.metricas(*total)["IoU"], "val_F1": E.metricas(*total)["Dice"],
            **{f"val_IoU_{k}": E.metricas(*v)["IoU"] for k, v in c.items()}}


def evaluar_externo(modelo, modo, cache, stats):
    r = {}
    if modo == "agua":
        cb = np.zeros(4)
        for f in sorted((C.BOLIVIA / "S1Hand").glob("*_S1Hand.tif")):
            post, _ = I.leer_escena(f)
            ref = rasterio.open(C.BOLIVIA / "LabelHand" / f.name.replace("S1Hand", "LabelHand")).read(1)
            prob, v = I.probabilidad(modelo, "agua", stats, post, None, DISP)
            m = v & (ref != -1)
            cb += E.conteos(prob[m] >= C.UMBRAL, ref[m] == 1)
        r["bolivia_IoU"] = E.metricas(*cb)["IoU"]
    for clave in ["l17", "l23"]:
        x = np.load(cache / f"{clave}_{modo}.npy", mmap_mode="r")
        pred = I.predecir_ventanas(modelo, x, DISP) >= C.UMBRAL
        tierra, oscuro = np.load(cache / f"{clave}_tierra.npy"), np.load(cache / f"{clave}_oscuro_ambas.npy")
        hand = np.load(cache / f"{clave}_hand.npy")
        r[f"{clave}_agua_tierra_%"] = 100 * pred[tierra].mean()
        r[f"{clave}_agua_tierra_HAND_%"] = 100 * (pred & hand)[tierra].mean()
        r[f"{clave}_falsos_en_oscuro_%"] = 100 * pred[oscuro].mean()
        if clave == "l17":
            ref = np.load(cache / "l17_ref.npy")
            m = ref != -1
            r["l17_IoU_EMS_HAND"] = E.metricas(*E.conteos((pred & hand)[m], ref[m] == 1))["IoU"]
            r["l17_recall_EMS"] = E.metricas(*E.conteos(pred[m], ref[m] == 1))["Recall"]
        del x, pred
    return r


def experimento(nombre, modo, train, val, cache, stats, pasos):
    ruta = EV / "experimentos" / f"{nombre}.json"
    if ruta.exists():
        return json.load(open(ruta))
    E.fijar_semilla()
    kw = dict(num_workers=C.NUM_WORKERS, persistent_workers=C.NUM_WORKERS > 0, pin_memory=DISP == "cuda")
    dl = DataLoader(E.Parches(train, modo, stats, True),
                    batch_sampler=PasosFijos(np.flatnonzero(train.positivo), len(train), C.LOTE, pasos), **kw)
    dl_val = DataLoader(E.Parches(val, modo, stats, False), batch_size=C.LOTE, **kw)
    modelo = E.crear_modelo(ENCODER, modo).to(DISP)
    opt = torch.optim.AdamW(modelo.parameters(), lr=C.LR, weight_decay=1e-4)
    esc = torch.amp.GradScaler(enabled=DISP == "cuda")
    mejor, mejor_estado, curva, t0 = -1, None, [], time.time()
    for ep in range(1, EPOCAS + 1):
        modelo.train()
        for x, y, m in dl:
            x, y, m = x.to(DISP), y.to(DISP), m.to(DISP)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(DISP, enabled=DISP == "cuda"):
                logits = modelo(x)
            l = E.perdida(logits.float(), y, m)
            esc.scale(l).backward(); esc.step(opt); esc.update()
        iou = E.evaluar(modelo, dl_val, DISP)["IoU"]
        curva.append(round(iou, 4))
        if iou > mejor:
            mejor, mejor_estado = iou, {k: v.detach().clone() for k, v in modelo.state_dict().items()}
    modelo.load_state_dict(mejor_estado)
    res = {"experimento": nombre, "modo": modo, "parches_train": len(train), "positivos_train": int(train.positivo.sum()),
           "datasets_train": "+".join(sorted(train.dataset.unique())), "curva_val_IoU": curva,
           "minutos": round((time.time() - t0) / 60, 1)}
    res.update(evaluar_val_por_fuente(modelo, modo, val, stats))
    res.update(evaluar_externo(modelo, modo, cache, stats))
    ruta.parent.mkdir(exist_ok=True)
    json.dump(res, open(ruta, "w"), indent=1)
    log(f"4. {nombre}: val IoU {res['val_IoU']:.3f} · " +
        " · ".join(f"{k} {v:.3f}" for k, v in res.items() if k.startswith(("bolivia", "l17_IoU", "l23_agua_tierra_%", "l23_falsos"))))
    del modelo, dl, dl_val
    torch.cuda.empty_cache()
    return res


def main():
    items = D.listar_items()
    inv = etapa_inventario(items)
    etapa_radiometria(items)
    indice, stats = etapa_parches(inv)
    cache = preparar_lima(stats)
    log("4. caché de Lima lista")
    resultados = []
    for modo in C.MODOS:
        train, val = E.filtrar(indice, modo)
        pasos = len(train) // C.LOTE
        for frac in FRACCIONES:
            sub = train if frac == 1 else train.groupby("evento", group_keys=False).sample(frac=frac, random_state=C.SEMILLA)
            resultados.append(experimento(f"{modo}_frac{int(frac * 100):03d}", modo, sub.reset_index(drop=True), val, cache, stats, pasos))
        for ds in sorted(train.dataset.unique()):
            sub = train[train.dataset != ds].reset_index(drop=True)
            resultados.append(experimento(f"{modo}_sin_{ds}", modo, sub, val, cache, stats, pasos))
    pd.DataFrame(resultados).to_csv(EV / "4_experimentos.csv", index=False)
    log("Umbral Otsu Lima 2017:", round(json.load(open(cache / "meta.json"))["otsu_17"], 1))
    log("FIN")


if __name__ == "__main__":
    main()
