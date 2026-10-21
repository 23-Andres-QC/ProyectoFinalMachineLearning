"""Lectura de Kuro Siwo, partición por bloques, inventario de parches, muestreo por evento y normalización.

Cada tesela se convierte a un formato común:
    pre, post : (2, H, W) en dB, canales [VV, VH]; pre es None si la fuente no tiene imagen previa
    lab       : (H, W) uint8 con las clases de config (0 sin agua, 1 permanente, 2 inundación abierta, 3 urbana)
    val       : (H, W) bool, píxeles con etiqueta e imagen válidas
"""
import json, random
from functools import lru_cache
from pathlib import Path

import numpy as np, pandas as pd, rasterio
from rasterio.warp import reproject, transform_bounds, Resampling
from rasterio.transform import array_bounds
from scipy.spatial import cKDTree
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


# ---------------------------------------------------------------- agua permanente (JRC)

def tesela_jrc(lon, lat):
    """Nombre de la tesela JRC de 10° que contiene (lon, lat); se nombran por su esquina superior izquierda."""
    x, y = int(np.floor(lon / 10) * 10), int(np.ceil(lat / 10) * 10)
    return f"{abs(x)}{'E' if x >= 0 else 'W'}_{abs(y)}{'N' if y >= 0 else 'S'}"


def _grilla_etiqueta(dataset, item):
    """Ráster cuya grilla (nativa) tiene la etiqueta del item."""
    return next(Path(item).glob("MK0_MLU_*.tif"))


def teselas_jrc_necesarias(items):
    teselas = set()
    for it in items.itertuples():
        with rasterio.open(_grilla_etiqueta(it.dataset, it.item)) as s:
            w, so, e, n = transform_bounds(s.crs, "EPSG:4326", *s.bounds)
        teselas |= {tesela_jrc(x, y) for x in (w, e) for y in (so, n)}
    return sorted(teselas)


@lru_cache(None)
def _limites_jrc():
    lim = []
    for r in sorted(C.JRC_GLOBAL.glob("*.tif")):
        with rasterio.open(r) as s:
            lim.append((r, s.bounds))
    return lim


def jrc_en_grilla(forma, transform, crs):
    """Ocurrencia de agua JRC (0-100 %) en la grilla dada; NaN donde no hay tesela o dato."""
    w, s, e, n = transform_bounds(crs, "EPSG:4326", *array_bounds(*forma, transform))
    out = np.full(forma, np.nan, "float32")
    for r, b in _limites_jrc():
        if b.left < e and b.right > w and b.bottom < n and b.top > s:
            tmp = np.full(forma, np.nan, "float32")
            with rasterio.open(r) as src:
                reproject(rasterio.band(src, 1), tmp, dst_transform=transform, dst_crs=crs,
                          resampling=Resampling.bilinear, src_nodata=255, dst_nodata=np.nan)
            out = np.where(np.isnan(out), tmp, out)
    return out


def jrc_item(dataset, item, cache=C.PREPARADO / "jrc"):
    """Ocurrencia JRC en la grilla nativa de la etiqueta del item (uint8, 255 = sin dato), guardada en disco."""
    ref = _grilla_etiqueta(dataset, item)
    ruta = Path(cache) / dataset / f"{Path(item).name}.npz"
    if ruta.exists():
        return np.load(ruta)["jrc"]
    with rasterio.open(ref) as s:
        occ = jrc_en_grilla((s.height, s.width), s.transform, s.crs)
    occ = np.where(np.isnan(occ), 255, np.round(occ)).astype("uint8")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(ruta, jrc=occ)
    return occ


def listar_items():
    """Un registro por tesela de Kuro Siwo de los eventos de EVENTOS_KS, con su partición."""
    filas = []
    for info in sorted(C.KUROSIWO.glob("*/**/info.json")):
        p = info.parent
        act = json.load(open(info))["actid"]
        if act in C.EVENTOS_KS and all(list(p.glob(f"{k}_*.tif")) for k in ["MS1_IVV", "MS1_IVH", "MK0_MLU", "MK0_MNA"]):
            filas.append(dict(dataset="kurosiwo", evento=C.EVENTOS_KS[act], item=str(p),
                              tiene_pre=bool(list(p.glob("SL1_IVV_*.tif")) and list(p.glob("SL1_IVH_*.tif")))))
    items = pd.DataFrame(filas)
    if C.MAX_ITEMS_EVENTO:
        items = items.sample(frac=1, random_state=C.SEMILLA).groupby("evento").head(C.MAX_ITEMS_EVENTO)
    return particion_por_bloques(items.reset_index(drop=True))


def particion_por_bloques(items):
    """Validación = bloques de VAL_BLOQUE_KM km de VAL_EVENTO elegidos al azar hasta cubrir VAL_FRAC de sus teselas.
    Las teselas de entrenamiento que tocan a una de validación se descartan para que no compartan bordes."""
    items = items.assign(particion="train")
    ev = items[items.evento == C.VAL_EVENTO]
    xy = []
    for it in ev.itertuples():
        with rasterio.open(_grilla_etiqueta("kurosiwo", it.item)) as s:
            b = s.bounds
            xy.append(((b.left + b.right) / 2, (b.bottom + b.top) / 2, b.right - b.left))
    xy = np.array(xy)
    lado = C.VAL_BLOQUE_KM * 1000
    bloque = pd.Series([f"{int(x // lado)}_{int(y // lado)}" for x, y, _ in xy], index=ev.index)
    rng = random.Random(C.SEMILLA)
    orden = sorted(bloque.unique())
    rng.shuffle(orden)
    val = []
    for b in orden:
        if len(val) >= C.VAL_FRAC * len(ev):
            break
        val += bloque.index[bloque == b].tolist()
    items.loc[val, "particion"] = "val"
    tr = ev.index.difference(val)
    if len(val) and len(tr):
        pos = pd.Series(range(len(ev)), index=ev.index)
        d, _ = cKDTree(xy[pos[val], :2]).query(xy[pos[tr], :2])
        tocan = tr[d < 1.1 * np.median(xy[:, 2])]          # centros a menos de ~1 tesela de distancia
        items = items.drop(tocan)
    return items.reset_index(drop=True)


def leer_etiqueta(dataset, item):
    """Lectura barata (solo etiquetas) para el inventario. MK0_MLU: 0 sin agua, 1 permanente, 2 inundación, 3 inválido."""
    mlu, mna = _ks_capa(item, "MK0_MLU"), _ks_capa(item, "MK0_MNA")
    return np.where(mlu == 3, 0, mlu).astype("uint8"), (mna == 1) & (mlu != 3)


def leer_item(dataset, item):
    """Lectura completa: imágenes en dB (Kuro Siwo viene en potencia lineal) + etiqueta + máscaras de validez."""
    lab, val = leer_etiqueta(dataset, item)
    crudo = np.stack([_ks_capa(item, "MS1_IVV"), _ks_capa(item, "MS1_IVH")])
    val &= (crudo > 0).all(0)
    post = a_db(crudo)
    pre = None
    if list(Path(item).glob("SL1_IVV_*.tif")):
        crudo_pre = np.stack([_ks_capa(item, "SL1_IVV"), _ks_capa(item, "SL1_IVH")])
        pre = np.where((crudo_pre > 0).all(0), a_db(crudo_pre), np.nan)
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


def contar_ventanas(val):
    """Ventanas T×T con al menos FRAC_VALIDA_MIN de píxeles válidos (las que entrarían al inventario)."""
    v = _pad(val.astype("uint8"))
    return sum(v[i:i+C.T, j:j+C.T].mean() >= C.FRAC_VALIDA_MIN for i, j in _ventanas(v.shape))


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
    """Tope de parches por evento y partición manteniendo una proporción de parches con agua."""
    rng = random.Random(semilla)
    elegidos = []
    for _, g in inv.groupby(["evento", "particion"], sort=True):
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


def extraer_parches(seleccion, salida=C.PREPARADO / "parches"):
    """Lee cada item una sola vez y guarda sus ventanas elegidas como .npz (float16).
    Si se interrumpe, al volver a llamarla reutiliza los items cuyos parches ya están completos."""
    filas = []
    for (ds, ev, item), g in tqdm(seleccion.groupby(["dataset", "evento", "item"], sort=False),
                                  total=seleccion[["item"]].drop_duplicates().shape[0], desc="parches"):
        carpeta = Path(salida) / ds / ev
        nombre = Path(item).name
        rutas = [carpeta / f"{nombre}_{r.i}_{r.j}.npz" for r in g.itertuples()]
        previas = _reutilizar(rutas, ds, ev, g.particion.iloc[0]) if all(r.exists() for r in rutas) else None
        if previas is not None:
            filas += [dict(f, item=item) for f in previas]
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
            filas.append(dict(_fila_parche(ruta, ds, ev, r.particion, l, v, vp), item=item))
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
