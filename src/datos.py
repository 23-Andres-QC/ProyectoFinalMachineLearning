"""Lectura de las fuentes internacionales, inventario de parches, muestreo por evento y normalización.

Cada fuente se convierte a un formato común:
    pre, post : (2, H, W) en dB, canales [VV, VH]; pre es None si la fuente no tiene imagen previa
    lab       : (H, W) uint8 con las clases de config (0 sin agua, 1 permanente, 2 inundación abierta, 3 urbana)
    val       : (H, W) bool, píxeles con etiqueta e imagen válidas
"""
import json, re, random
from pathlib import Path

import numpy as np, pandas as pd, rasterio
from scipy.ndimage import zoom
from tqdm.auto import tqdm

from . import config as C


def leer(ruta, bandas=None):
    with rasterio.open(ruta) as s:
        return s.read(bandas).astype("float32")


def a_db(x):
    return 10 * np.log10(np.clip(x, 1e-6, None))


def validos_db(img):
    return np.isfinite(img).all(0) & (img > C.DB_INVALIDO).all(0)


# ---------------------------------------------------------------- fuentes

def _ks_capa(p, clave):
    f = sorted(Path(p).glob(f"{clave}_*.tif"))
    return leer(f[0])[0] if f else None


def _us_gt(ruta):
    ruta = Path(ruta)
    return ruta.parent.parent / "GT" / ruta.name.replace("_SAR.tif", "_GT.tif")


def listar_items():
    """Devuelve un DataFrame con un registro por archivo/tesela de cada fuente internacional."""
    filas = []
    for r in sorted((C.COLOMBIA / "S1Weak").glob("*_S1Weak.tif")):
        etq = C.COLOMBIA / "S1OtsuLabelWeak" / r.name.replace("S1Weak", "S1OtsuLabelWeak")
        if etq.exists():
            filas.append(dict(dataset="colombia", evento="colombia", item=str(r), tiene_pre=False))
    for info in sorted(C.KUROSIWO.glob("*/**/info.json")):
        p = info.parent
        if all(list(p.glob(f"{k}_*.tif")) for k in ["MS1_IVV", "MS1_IVH", "MK0_MLU", "MK0_MNA"]):
            act = json.load(open(info))["actid"]
            filas.append(dict(dataset="kurosiwo", evento=C.EVENTOS_KS[act], item=str(p),
                              tiene_pre=bool(list(p.glob("SL1_IVV_*.tif")) and list(p.glob("SL1_IVH_*.tif")))))
    for r in sorted(C.URBANSAR.glob("*/SAR/*_SAR.tif")):
        if _us_gt(r).exists():
            ev = re.match(r"\d+_[A-Za-z]+", r.name).group()
            filas.append(dict(dataset="urbansar", evento=ev, item=str(r), tiene_pre=True))
    items = pd.DataFrame(filas)
    if C.MAX_ITEMS_EVENTO:
        items = items.sample(frac=1, random_state=C.SEMILLA).groupby("evento").head(C.MAX_ITEMS_EVENTO)
    items = items.reset_index(drop=True)
    items["particion"] = np.where(items.evento.isin(C.EVENTOS_VAL), "val", "train")
    return items


def leer_etiqueta(dataset, item):
    """Lectura barata (solo etiquetas) para el inventario."""
    if dataset == "colombia":
        r = Path(item)
        e = leer(r.parent.parent / "S1OtsuLabelWeak" / r.name.replace("S1Weak", "S1OtsuLabelWeak"))[0]
        return np.where(e == 1, C.AGUA_PERMANENTE, C.SIN_AGUA).astype("uint8"), e != -1
    if dataset == "kurosiwo":
        mlu, mna = _ks_capa(item, "MK0_MLU"), _ks_capa(item, "MK0_MNA")
        return np.where(mlu == 3, 0, mlu).astype("uint8"), (mna == 1) & (mlu != 3)
    gt = leer(_us_gt(item))[0]
    lab = np.select([gt == 1, gt == 2], [C.INUNDACION_ABIERTA, C.INUNDACION_URBANA], C.SIN_AGUA).astype("uint8")
    # UrbanSARFloods está a ~20 m: se lleva a la grilla de 10 m del resto.
    return zoom(lab, 2, order=0), np.ones((lab.shape[0] * 2, lab.shape[1] * 2), bool)


def leer_item(dataset, item):
    """Lectura completa: imágenes en dB + etiqueta + máscaras de validez."""
    lab, val = leer_etiqueta(dataset, item)
    if dataset == "colombia":
        post, pre = leer(item), None
    elif dataset == "kurosiwo":
        crudo = np.stack([_ks_capa(item, "MS1_IVV"), _ks_capa(item, "MS1_IVH")])
        val &= (crudo > 0).all(0)
        post = a_db(crudo)
        pre = None
        if list(Path(item).glob("SL1_IVV_*.tif")):
            crudo_pre = np.stack([_ks_capa(item, "SL1_IVV"), _ks_capa(item, "SL1_IVH")])
            pre = np.where((crudo_pre > 0).all(0), a_db(crudo_pre), np.nan)
    else:
        a = leer(item)  # b1-4 coherencia; b5 VH pre, b6 VV pre, b7 VH post, b8 VV post (dB)
        post = zoom(np.stack([a[7], a[6]]), (1, 2, 2), order=1)
        pre = zoom(np.stack([a[5], a[4]]), (1, 2, 2), order=1)
    val &= validos_db(post)
    val_pre = validos_db(pre) if pre is not None else np.zeros_like(val)
    return pre, post, lab, val, val_pre


# ---------------------------------------------------------------- parches

def _ventanas(forma):
    H, W = forma
    return [(i, j) for i in range(0, H + (-H) % C.T, C.T) for j in range(0, W + (-W) % C.T, C.T)]


def _pad(a, valor=0):
    H, W = a.shape[-2:]
    pads = [(0, 0)] * (a.ndim - 2) + [(0, (-H) % C.T), (0, (-W) % C.T)]
    return np.pad(a, pads, constant_values=valor)


def inventario(items):
    """Fracción válida y de agua de cada ventana T×T, leyendo solo etiquetas."""
    filas = []
    for it in tqdm(items.itertuples(), total=len(items), desc="inventario"):
        lab, val = leer_etiqueta(it.dataset, it.item)
        lab, val = _pad(lab), _pad(val.astype("uint8"))
        for i, j in _ventanas(lab.shape):
            v = val[i:i+C.T, j:j+C.T]
            fv = v.mean()
            if fv < C.FRAC_VALIDA_MIN:
                continue
            l = lab[i:i+C.T, j:j+C.T][v == 1]
            filas.append(dict(dataset=it.dataset, evento=it.evento, item=it.item, particion=it.particion,
                              tiene_pre=it.tiene_pre, i=i, j=j, frac_valida=fv,
                              frac_agua=(l > 0).mean(), frac_inundacion=(l >= 2).mean()))
    return pd.DataFrame(filas)


def muestrear(inv, maximo=C.MAX_PARCHES_EVENTO, frac_con=C.FRAC_CON_AGUA, semilla=C.SEMILLA):
    """Tope de parches por evento manteniendo una proporción de parches con agua."""
    rng = random.Random(semilla)
    elegidos = []
    for _, g in inv.groupby("evento", sort=True):
        idx_con = g.index[g.frac_agua > C.FRAC_AGUA_POSITIVO].tolist()
        idx_sin = g.index[g.frac_agua <= C.FRAC_AGUA_POSITIVO].tolist()
        rng.shuffle(idx_con), rng.shuffle(idx_sin)
        n = min(maximo, len(g))
        n_con = min(len(idx_con), round(n * frac_con))
        n_sin = min(len(idx_sin), n - n_con)
        n_con = min(len(idx_con), n - n_sin)
        elegidos += idx_con[:n_con] + idx_sin[:n_sin]
    return inv.loc[sorted(elegidos)].reset_index(drop=True)


def _fila_parche(ruta, ds, ev, particion, l, v, vp):
    return dict(ruta=str(ruta), dataset=ds, evento=ev, particion=particion,
                tiene_pre=bool(vp.mean() >= C.FRAC_VALIDA_MIN),
                frac_valida=v.mean(), frac_agua=(l > 0).sum() / v.sum(),
                frac_inundacion=(l >= 2).sum() / v.sum())


def _reutilizar(rutas, ds, ev, particion):
    """Filas de parches ya guardados en una corrida anterior; None si falta o está dañado alguno."""
    filas = []
    for ruta in rutas:
        try:
            with np.load(ruta) as d:
                filas.append(_fila_parche(ruta, ds, ev, particion, d["lab"], d["val"], d["val_pre"]))
        except Exception:
            return None
    return filas


def extraer_parches(seleccion, salida=C.SALIDA / "parches"):
    """Lee cada item una sola vez y guarda sus ventanas elegidas como .npz (float16).
    Si se interrumpe, al volver a llamarla reutiliza los items cuyos parches ya están completos."""
    filas = []
    for (ds, ev, item), g in tqdm(seleccion.groupby(["dataset", "evento", "item"], sort=False),
                                  total=seleccion[["item"]].drop_duplicates().shape[0], desc="parches"):
        carpeta = Path(salida) / ds / ev
        nombre = Path(item).stem if ds != "kurosiwo" else Path(item).name
        rutas = [carpeta / f"{nombre}_{r.i}_{r.j}.npz" for r in g.itertuples()]
        previas = _reutilizar(rutas, ds, ev, g.particion.iloc[0]) if all(r.exists() for r in rutas) else None
        if previas is not None:
            filas += previas
            continue
        pre, post, lab, val, val_pre = leer_item(ds, item)
        if pre is None:
            pre = np.full_like(post, np.nan)
        img = _pad(np.concatenate([pre, post]), np.nan)
        lab, val, val_pre = _pad(lab), _pad(val.astype("uint8")), _pad(val_pre.astype("uint8"))
        carpeta.mkdir(parents=True, exist_ok=True)
        for r, ruta in zip(g.itertuples(), rutas):
            s = (slice(r.i, r.i + C.T), slice(r.j, r.j + C.T))
            v, vp = val[s], val_pre[s] & val[s]
            if v.mean() < C.FRAC_VALIDA_MIN:
                continue
            l = lab[s] * v
            np.savez_compressed(ruta, img=img[(slice(None),) + s].astype("float16"), lab=l, val=v, val_pre=vp)
            filas.append(_fila_parche(ruta, ds, ev, r.particion, l, v, vp))
    return pd.DataFrame(filas)


def estadisticas(indice):
    """Media y desviación por canal, solo con píxeles válidos de Train."""
    s, s2, n = np.zeros(4), np.zeros(4), np.zeros(4)
    for r in tqdm(indice.query("particion == 'train'").itertuples(), desc="estadísticas"):
        d = np.load(r.ruta)
        img = d["img"].astype("float64")
        for c, m in zip(range(4), [d["val_pre"]] * 2 + [d["val"]] * 2):
            x = np.clip(img[c][m == 1], C.DB_MIN, C.DB_MAX)
            s[c] += x.sum(); s2[c] += (x ** 2).sum(); n[c] += x.size
    media = s / np.maximum(n, 1)
    return {"canales": C.NOMBRES_CANALES, "media": media.tolist(),
            "std": np.sqrt(s2 / np.maximum(n, 1) - media ** 2).tolist(), "pixeles": n.tolist()}
