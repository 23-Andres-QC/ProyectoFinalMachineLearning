"""Experimentos sobre los datos de entrenamiento: ¿aporta usar más datos y qué aporta cada fuente?

Consume lo que deja preparacion_datos.ipynb en Data/procesado/preparado/ (no lee datos crudos).
La calidad de cada evento (etiquetas, radiometría, similitud con Lima) ya se evalúa en ese notebook.
Experimentos con U-Net MobileNetV2 y presupuesto fijo de pasos, guardados en Data/procesado/resultados/evaluacion_datos/
(cada uno se salta si ya existe):
  - curva de aprendizaje (10, 25, 50 y 100 % de los parches de train, por evento)
  - ablación: entrenar sin cada evento
Cada modelo se mide en validación (por fuente), Bolivia y Lima (2017 y 2023).

Uso:  python scripts/evaluar_datos.py
"""
import sys, json, time, warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

import numpy as np, pandas as pd, torch
from torch.utils.data import DataLoader

from src import config as C, datos as D, entrenamiento as E, inferencia as I, preparacion as P

EV = C.RESULTADOS / "evaluacion_datos"
EV.mkdir(parents=True, exist_ok=True)
DISP = "cuda" if torch.cuda.is_available() else "cpu"
ENCODER = "mobilenet_v2"
EPOCAS = 6                      # cada "época" = pasos de una época completa al 100 %
FRACCIONES = [0.1, 0.25, 0.5, 1.0]
if C.MAX_ITEMS_EVENTO:  # modo rápido
    EPOCAS, FRACCIONES = 1, [0.5, 1.0]


def log(*a):
    texto = " ".join(str(x) for x in a)
    print(texto, flush=True)
    with open(EV / "evaluacion.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + texto + "\n")


# ------------------------------------------------------------------ 4. experimentos
class PasosFijos(E.LotesBalanceados):
    def __init__(self, positivos, n_total, lote, pasos):
        super().__init__(positivos, n_total, lote)
        self.pasos = pasos

    def __len__(self):
        return self.pasos


def preparar_lima(stats):
    """Entradas normalizadas de Lima (desde las escenas preparadas) guardadas como memmap para no saturar la RAM."""
    cache = EV / "cache"
    cache.mkdir(exist_ok=True)
    if not (cache / "meta.json").exists():
        meta = {}
        for clave, nombre in [("l17", "lima_2017"), ("l23", "lima_2023")]:
            capas, _ = P.cargar_escena(C.PRUEBAS / f"{nombre}.npz")
            x, p = capas["post"], capas["pre"]
            v = D.validos_db(x) & D.validos_db(p)
            entrada = [p[0], p[1], x[0], x[1]]
            for modo, cfg in C.MODOS.items():
                out = np.lib.format.open_memmap(cache / f"{clave}_{modo}.npy", "w+", "float32", (len(cfg["canales"]),) + v.shape)
                for k, c in enumerate(cfg["canales"]):
                    out[k] = E.normalizar(entrada[c][None], v, stats, [c])[0]
                out.flush(); del out
            tierra = (capas["dem"] > 1) & v
            np.save(cache / f"{clave}_tierra.npy", tierra)
            np.save(cache / f"{clave}_oscuro_ambas.npy", (x[1] < -20) & (p[1] < -20) & tierra)
            np.save(cache / f"{clave}_hand.npy", capas["hand"] < C.HAND_MAX)
            if clave == "l17":
                ref = capas["ref"].copy()
                ref[~v] = -1
                np.save(cache / "l17_ref.npy", ref)
                meta["otsu_17"] = float(I.otsu(x[1][ref != -1]))
                np.save(cache / "l17_otsu.npy", x[1] < meta["otsu_17"])
            del x, p, v, capas
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
        bol = np.load(C.PRUEBAS / "bolivia.npz")
        for post, ref in zip(bol["post"], bol["ref"]):
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
    indice = pd.read_csv(C.PREPARADO / "indice.csv")
    stats = json.load(open(C.PREPARADO / "stats.json"))
    cache = preparar_lima(stats)
    log("4. caché de Lima lista")
    resultados = []
    for modo in C.MODOS:
        train, val = E.filtrar(indice, modo)
        pasos = len(train) // C.LOTE
        for frac in FRACCIONES:
            sub = train if frac == 1 else train.groupby("evento", group_keys=False).sample(frac=frac, random_state=C.SEMILLA)
            resultados.append(experimento(f"{modo}_frac{int(frac * 100):03d}", modo, sub.reset_index(drop=True), val, cache, stats, pasos))
        for ev in sorted(train.evento.unique()):
            sub = train[train.evento != ev].reset_index(drop=True)
            resultados.append(experimento(f"{modo}_sin_{ev}", modo, sub, val, cache, stats, pasos))
    pd.DataFrame(resultados).to_csv(EV / "4_experimentos.csv", index=False)
    log("Umbral Otsu Lima 2017:", round(json.load(open(cache / "meta.json"))["otsu_17"], 1))
    log("FIN")


if __name__ == "__main__":
    main()
