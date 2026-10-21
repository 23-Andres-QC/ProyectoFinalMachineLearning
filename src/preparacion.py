"""Evaluación de calidad de las fuentes y preparación de los datos de prueba (Bolivia, Lima).

Todo lo que produce queda en config.PREPARADO; pipeline_inundaciones.ipynb solo lee de ahí.
"""
import json, time
from collections import defaultdict
from pathlib import Path

import numpy as np, pandas as pd, rasterio, requests, geopandas as gpd
import matplotlib.pyplot as plt
from affine import Affine
from rasterio.crs import CRS
from scipy import ndimage
from tqdm.auto import tqdm

from . import config as C, datos as D, inferencia as I

BINS = np.arange(-30, 5.01, 0.5)


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


# ---------------------------------------------------------------- JRC

def descargar_jrc(teselas, destino=C.JRC_GLOBAL):
    url = "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/occurrence_{}v1_4_2021.tif"
    Path(destino).mkdir(parents=True, exist_ok=True)
    for t in teselas:
        ruta = Path(destino) / f"occurrence_{t}v1_4_2021.tif"
        for intento in range(1, 6):
            try:
                with requests.get(url.format(t), stream=True, timeout=120) as r:
                    r.raise_for_status()
                    tam = int(r.headers.get("Content-Length", 0))
                    if ruta.exists() and ruta.stat().st_size == tam:
                        break
                    with open(ruta, "wb") as f:
                        for trozo in r.iter_content(1024 * 1024):
                            f.write(trozo)
                print(f"JRC {t}: {tam / 1e6:.1f} MB")
                break
            except requests.exceptions.RequestException as e:
                print(f"JRC {t}: se cortó ({type(e).__name__}), reintento {intento}")
                time.sleep(10)
    D._limites_jrc.cache_clear()


# ---------------------------------------------------------------- calidad por evento

def muestra_calidad(items, n=C.ITEMS_CALIDAD):
    """Hasta `n` items al azar por evento: con eso se evalúa la calidad, sin leer el dataset completo."""
    return (items.groupby("evento", group_keys=False)
            .apply(lambda g: g.sample(min(len(g), n), random_state=C.SEMILLA)).reset_index(drop=True))


def muestra_inventario(items, cal, objetivo=C.VENTANAS_INVENTARIO):
    """Items al azar de los eventos que sirven, los justos para tener unas `objetivo` ventanas por evento."""
    partes = []
    for f in cal[cal.sirve_agua | cal.sirve_cambio].itertuples():
        g = items[items.evento == f.evento]
        n = min(len(g), int(np.ceil(objetivo / max(f.ventanas_por_item, 1e-6))))
        partes.append(g.sample(n, random_state=C.SEMILLA))
    return pd.concat(partes).reset_index(drop=True)


def evaluar_calidad(muestra, items, vh_lima):
    """Una fila por evento con indicadores de si sus etiquetas sirven para aprender a detectar agua.
    Se mide sobre la muestra; las ventanas del evento se estiman con las ventanas por item de la muestra."""
    h_lima = hist(vh_lima)
    filas = []
    for (ds, ev), g in tqdm(muestra.groupby(["dataset", "evento"]), desc="calidad"):
        acc, n_ventanas = defaultdict(list), 0
        for it in g.itertuples():
            pre, post, lab, val, val_pre = D.leer_item(ds, it.item)
            n_ventanas += D.contar_ventanas(val)
            occ = D.jrc_item(ds, it.item)
            perm = val & (occ >= C.JRC_PERMANENTE) & (occ != 255)
            acc["perm"].append(lab[perm] > 0)
            et, n = ndimage.label((lab > 0) & val, np.ones((3, 3)))
            if n:
                acc["manchas"].append(ndimage.sum(et > 0, et, np.arange(1, n + 1)))
            vh = post[1]
            acc["agua"].append(vh[val & (lab > 0)][::4]); acc["no_agua"].append(vh[val & (lab == 0)][::4])
            if pre is not None:
                mp, d = val & val_pre, vh - pre[1]
                acc["dvh_inund"].append(d[mp & (lab >= 2)][::4]); acc["dvh_resto"].append(d[mp & (lab < 2)][::4])
        cat = {k: np.concatenate(v) for k, v in acc.items()}
        a, na = cat["agua"], cat["no_agua"]
        m = cat.get("manchas", np.zeros(0))          # tamaño de cada mancha de agua en píxeles de 10 m (100 m²)
        total = int((items.evento == ev).sum())
        fila = dict(dataset=ds, evento=ev, particion="+".join(sorted(items[items.evento == ev].particion.unique())),
                    origen=C.ORIGEN_ETIQUETAS[ds],
                    tiene_pre=bool(g.tiene_pre.all()), items=total, items_muestra=len(g),
                    ventanas_por_item=n_ventanas / len(g), ventanas=round(n_ventanas / len(g) * total),
                    px_permanente=len(cat["perm"]),
                    agua_permanente_pct=100 * cat["perm"].mean() if len(cat["perm"]) >= 1000 else np.nan,
                    agua_oscura_pct=100 * (a < C.VH_AGUA).mean() if len(a) else np.nan,
                    manchas=len(m), mancha_mediana_m2=float(np.median(m) * 100) if len(m) else np.nan,
                    area_manchas_lt_1ha_pct=100 * m[m < 100].sum() / max(m.sum(), 1),
                    area_cuerpos_gt_100ha_pct=100 * m[m >= 10000].sum() / max(m.sum(), 1),
                    vh_mediana_agua=float(np.median(a)) if len(a) else np.nan,
                    vh_mediana_no_agua=float(np.median(na)),
                    auc_vh=auc(-a, -na),
                    tierra_oscura_pct=100 * (na < -20).mean(),
                    similitud_lima=float(np.minimum(hist(na), h_lima).sum()),
                    auc_dvh=auc(-cat["dvh_inund"], -cat["dvh_resto"]) if "dvh_inund" in cat else np.nan)
        filas.append(fila)
    return decidir(pd.DataFrame(filas))


def decidir(cal):
    """Aplica los criterios de config.CALIDAD y agrega sirve_agua / sirve_cambio con el motivo."""
    q = C.CALIDAD
    sa, sc, ma, mc = [], [], [], []
    for f in cal.itertuples():
        agua, cambio = [], []
        if f.origen.startswith("automática"):
            agua.append("etiqueta automática"); cambio.append("etiqueta automática")
        if f.ventanas < q["ventanas_min"]:
            agua.append("pocas ventanas"); cambio.append("pocas ventanas")
        if not np.isnan(f.agua_permanente_pct) and f.agua_permanente_pct < q["agua_permanente_min"]:
            agua.append(f"solo {f.agua_permanente_pct:.0f} % del agua permanente etiquetada")
        if not f.agua_oscura_pct >= q["agua_oscura_min"]:
            agua.append(f"solo {f.agua_oscura_pct:.0f} % del agua etiquetada es oscura en VH")
        if not f.tiene_pre:
            cambio.append("sin imagen previa")
        elif not f.auc_dvh >= q["auc_dvh_min"]:
            cambio.append(f"la inundación no se separa por ΔVH (AUC {f.auc_dvh:.2f})")
        sa.append(not agua); sc.append(not cambio)
        ma.append("; ".join(agua) or "sirve"); mc.append("; ".join(cambio) or "sirve")
    return cal.assign(sirve_agua=sa, sirve_cambio=sc, motivo_agua=ma, motivo_cambio=mc)


def marcar_modos(indice, cal):
    """Columnas booleanas `agua` y `cambio`: si el parche se usa en cada modo."""
    m = cal.set_index("evento")
    indice = indice.assign(agua=indice.evento.map(m.sirve_agua).fillna(False).astype(bool),
                           cambio=indice.evento.map(m.sirve_cambio).fillna(False).astype(bool))
    indice["cambio"] &= indice.tiene_pre
    return indice


# ---------------------------------------------------------------- pruebas (Bolivia y Lima)

def guardar_escena(ruta, perfil, **capas):
    meta = {"crs": perfil["crs"].to_wkt(), "transform": list(perfil["transform"])[:6],
            "height": perfil["height"], "width": perfil["width"]}
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    np.savez(ruta, perfil=np.array(json.dumps(meta)), **capas)


def cargar_escena(ruta):
    """Devuelve (capas, perfil); las capas se leen del disco al pedirlas (capas['post'])."""
    capas = np.load(ruta)
    m = json.loads(str(capas["perfil"]))
    perfil = {"driver": "GTiff", "crs": CRS.from_wkt(m["crs"]), "transform": Affine(*m["transform"]),
              "height": m["height"], "width": m["width"], "count": 1, "dtype": "float32"}
    return capas, perfil


def referencia_emsn038(perfil):
    """1 = zona de inundación potencial + riberas de EMSN038, 0 = resto, -1 = fuera del área cartografiada."""
    gdb = C.EMSN038
    agua = pd.concat([gpd.read_file(gdb, layer=c) for c in ["Potential_Maximum_flood", "Riverbank"]])
    zona = gpd.read_file(gdb, layer="EMSN038_AOI").overlay(gpd.read_file(gdb, layer="Footprints"), how="intersection")
    ref = I.rasterizar(agua, perfil).astype("int8")
    ref[I.rasterizar(zona, perfil) == 0] = -1
    return ref


ESCENAS_LIMA = {"lima_2017": ("lima_2017_0317", "lima_2017_0305"), "lima_2023": ("lima_2023_0316", "lima_2023_0304")}


def preparar_lima(rehacer=False):
    """Escena durante + previa en la misma grilla, con HAND, DEM y JRC; en 2017 también la referencia EMSN038."""
    for clave, (post, pre) in ESCENAS_LIMA.items():
        ruta = C.PRUEBAS / f"{clave}.npz"
        if ruta.exists() and not rehacer:
            continue
        x, perfil = I.leer_escena(C.LIMA / f"{post}.tif")
        capas = dict(post=x, pre=I.leer_en_grilla(C.LIMA / f"{pre}.tif", perfil),
                     hand=I.a_grilla(C.HAND, perfil).astype("float16"),
                     dem=I.a_grilla(C.DEM, perfil).astype("float16"),
                     # vecino más cercano: 255 (sin dato, mar abierto) no debe mezclarse con las ocurrencias de la costa
                     jrc=I.a_grilla(C.JRC, perfil, I.Resampling.nearest).astype("float16"))
        if clave == "lima_2017":
            capas["ref"] = referencia_emsn038(perfil)
        guardar_escena(ruta, perfil, **capas)
        del x, capas


def preparar_bolivia(rehacer=False):
    """Los 15 chips con etiqueta manual: post (N, 2, H, W) en dB y ref (N, H, W) con -1 = sin etiqueta."""
    ruta = C.PRUEBAS / "bolivia.npz"
    if ruta.exists() and not rehacer:
        return
    nombres, post, ref = [], [], []
    for r in sorted((C.BOLIVIA / "S1Hand").glob("*_S1Hand.tif")):
        nombres.append(r.name.replace("_S1Hand.tif", ""))
        post.append(I.leer_escena(r)[0])
        ref.append(D.leer(C.BOLIVIA / "LabelHand" / r.name.replace("S1Hand", "LabelHand"))[0].astype("int8"))
    C.PRUEBAS.mkdir(parents=True, exist_ok=True)
    np.savez(ruta, nombres=np.array(nombres), post=np.stack(post), ref=np.stack(ref))


def preparar_distritos(rehacer=False):
    ruta = C.PRUEBAS / "distritos_lima.gpkg"
    if ruta.exists() and not rehacer:
        return
    d = gpd.read_file(C.EMSN038, layer="Admin_MINAM_BAS_LIM_DISTRITOS")
    d = d[d.NOMBPROV == "LIMA"][["NOMBDIST", "NOMBPROV", "geometry"]]
    d["geometry"] = d.geometry.force_2d()
    C.PRUEBAS.mkdir(parents=True, exist_ok=True)
    d.to_file(ruta, driver="GPKG")


def vh_tierra_lima(clave="lima_2023", paso=7):
    """VH durante el evento sobre tierra firme (DEM > 1 m), para comparar con la radiometría de cada fuente."""
    capas, _ = cargar_escena(C.PRUEBAS / f"{clave}.npz")
    x = capas["post"]
    m = D.validos_db(x) & (capas["dem"] > 1)
    return x[1][m][::paso]


# ---------------------------------------------------------------- ver cada fuente en su formato

def capas_crudas(dataset, item):
    """(nombre, archivo, banda) de cada capa del item tal como viene en el dataset original."""
    r = Path(item)
    if dataset == "bolivia":
        e = r.parent.parent / "LabelHand" / r.name.replace("S1Hand", "LabelHand")
        return [("VV (dB)", r, 1), ("VH (dB)", r, 2), ("etiqueta manual (-1/0/1)", e, 1)]
    if dataset == "kurosiwo":
        nombres = {"SL1_IVV": "VV antes (lineal)", "SL1_IVH": "VH antes (lineal)", "MS1_IVV": "VV durante (lineal)",
                   "MS1_IVH": "VH durante (lineal)", "MK0_MLU": "etiqueta (0/1 perm./2 inund./3 inválido)", "MK0_MNA": "válido (MNA)"}
        return [(n, next(r.glob(f"{k}_*.tif")), 1) for k, n in nombres.items() if list(r.glob(f"{k}_*.tif"))]
    if dataset == "lima":   # item = nombre de la escena procesada en SNAP
        return [("VV (dB)", C.LIMA / f"{item}.tif", 1), ("VH (dB)", C.LIMA / f"{item}.tif", 2)]
    raise ValueError(dataset)


def _leer_reducida(ruta, banda, max_lado=1024):
    with rasterio.open(ruta) as s:
        f = max(1, max(s.height, s.width) // max_lado)
        a = s.read(banda, out_shape=(s.height // f, s.width // f)).astype("float32")
        if s.nodata is not None and not np.isnan(s.nodata):
            a[a == s.nodata] = np.nan
        return a, s, f


def describir_capas(capas):
    """Tabla con el formato de cada capa: archivo, forma, tipo, resolución, CRS, nodata y rango de valores."""
    filas = []
    for nombre, ruta, banda in capas:
        a, s, _ = _leer_reducida(ruta, banda)
        v = a[np.isfinite(a)]
        unicos = np.unique(v) if s.dtypes[0].startswith(("int", "uint")) or len(np.unique(v[:5000])) <= 5 else []
        filas.append({"capa": nombre, "archivo": Path(ruta).name, "banda": f"{banda}/{s.count}",
                      "forma": f"{s.height}×{s.width}", "tipo": s.dtypes[0],
                      "resolución": f"{abs(s.res[0]):.3g} {'°' if s.crs and s.crs.is_geographic else 'm'}",
                      "crs": s.crs.to_string() if s.crs else None, "nodata": s.nodata,
                      "mín": v.min() if v.size else np.nan, "p50": np.median(v) if v.size else np.nan,
                      "máx": v.max() if v.size else np.nan,
                      "valores": ", ".join(f"{u:g}" for u in unicos[:8]) if 0 < len(unicos) <= 8 else ""})
    return pd.DataFrame(filas)


def mostrar_capas(capas, titulo=""):
    """Una imagen por capa; las continuas con estiramiento p2–p98 y las etiquetas con colores discretos."""
    fig, ejes = plt.subplots(1, len(capas), figsize=(3.1 * len(capas), 3.3), squeeze=False)
    for ax, (nombre, ruta, banda) in zip(ejes[0], capas):
        a, s, _ = _leer_reducida(ruta, banda)
        v = a[np.isfinite(a)]
        discreta = s.dtypes[0].startswith(("int", "uint")) or len(np.unique(v[:5000])) <= 5
        if discreta:
            im = ax.imshow(a, cmap="viridis", vmin=np.nanmin(a), vmax=max(np.nanmax(a), np.nanmin(a) + 1), interpolation="nearest")
        else:
            lo, hi = np.percentile(v, [2, 98]) if v.size else (0, 1)
            im = ax.imshow(a, cmap="gray", vmin=lo, vmax=hi)
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
        ax.set_title(nombre, fontsize=8)
        ax.axis("off")
    fig.suptitle(titulo, fontsize=10)
    plt.tight_layout()
    plt.show()


def describir_npz(ruta):
    """Variables de un .npz preparado: forma, tipo y rango."""
    d = np.load(ruta)
    filas = []
    for k in d.files:
        if k == "perfil":
            continue
        a = d[k]
        v = a[np.isfinite(a)] if a.dtype.kind == "f" else a.ravel()
        num = a.dtype.kind in "fiub"
        filas.append({"variable": k, "forma": "×".join(map(str, a.shape)), "tipo": str(a.dtype),
                      "MB": round(a.nbytes / 1e6, 1),
                      "mín": v.min() if num and v.size else "", "máx": v.max() if num and v.size else "",
                      "% NaN": round(100 * np.isnan(a).mean(), 2) if a.dtype.kind == "f" else ""})
    return pd.DataFrame(filas)


def mostrar_escena(ruta, titulo="", max_lado=1200):
    """Todas las capas de una escena preparada de Lima (submuestreada para dibujarla)."""
    capas, _ = cargar_escena(ruta)
    paneles = []
    for k in [k for k in capas.files if k != "perfil"]:
        a = capas[k]
        for c, nombre in ([(0, "VV"), (1, "VH")] if a.ndim == 3 else [(None, "")]):
            z = a[c] if c is not None else a
            r = max(1, max(z.shape) // max_lado)
            z = z[::r, ::r].astype("float32")
            estilo = {"post": ("gray", -25, 0), "pre": ("gray", -25, 0), "hand": ("viridis", 0, 30),
                      "dem": ("terrain", 0, 1500), "jrc": ("Blues", 0, 100), "ref": ("viridis", -1, 1)}[k]
            paneles.append((z, f"{k} {nombre}".strip(), *estilo))
    I.mostrar(paneles, titulo)


def ejemplo_por_evento(items, dataset, candidatos=10):
    """Una fila por evento del dataset: el item con más agua entre `candidatos` al azar, con etiqueta original y JRC."""
    filas = []
    for ev, g in items[items.dataset == dataset].groupby("evento"):
        cand = g.sample(min(len(g), candidatos), random_state=C.SEMILLA).item
        item = max(cand, key=lambda it: (D.leer_etiqueta(dataset, it)[0] > 0).mean())
        pre, post, lab, val, _ = D.leer_item(dataset, item)
        occ = D.jrc_item(dataset, item).astype("float32")
        occ[occ == 255] = np.nan
        filas.append((ev, Path(item).name, pre, post, np.where(val, lab.astype("int16"), -1), occ))
    fig, ejes = plt.subplots(len(filas), 5, figsize=(15, 3 * len(filas)), squeeze=False)
    for fila, (ev, nombre, pre, post, lab, occ) in zip(ejes, filas):
        paneles = [(pre[1] if pre is not None else None, "VH antes (dB)", "gray", -25, 0),
                   (post[1], "VH durante (dB)", "gray", -25, 0),
                   (post[1] - pre[1] if pre is not None else None, "ΔVH (dB)", "RdBu", -6, 6),
                   (lab, "etiqueta original (-1 inválido)", "viridis", -1, 3),
                   (occ, "JRC ocurrencia (%)", "Blues", 0, 100)]
        for ax, (z, t, cm, lo, hi) in zip(fila, paneles):
            if z is None:
                ax.text(0.5, 0.5, "sin imagen previa", ha="center", va="center"); ax.axis("off"); continue
            ax.imshow(z, cmap=cm, vmin=lo, vmax=hi, interpolation="nearest")
            ax.set_title(f"{ev} · {t}", fontsize=8)
            ax.axis("off")
        fila[0].text(-0.05, 0.5, nombre[:28], transform=fila[0].transAxes, rotation=90, ha="right", va="center", fontsize=7)
    fig.suptitle(f"{dataset}: un ejemplo por evento", fontsize=11)
    plt.tight_layout()
    plt.show()


def mostrar_emsn038():
    """Capas de EMSN038 que se usan (referencia de 2017 y distritos) sobre un mismo mapa."""
    gdb = C.EMSN038
    usadas = ["EMSN038_AOI", "Footprints", "Potential_Maximum_flood", "Riverbank", "Admin_MINAM_BAS_LIM_DISTRITOS"]
    capas = {c: gpd.read_file(gdb, layer=c).to_crs(32718) for c in usadas}
    capas["Admin_MINAM_BAS_LIM_DISTRITOS"] = capas["Admin_MINAM_BAS_LIM_DISTRITOS"].query("NOMBPROV == 'LIMA'")
    tabla = pd.DataFrame([{"capa": c, "objetos": len(g), "geometría": ", ".join(g.geom_type.unique()),
                           "km²": round(g.area.sum() / 1e6, 2), "columnas": ", ".join(g.columns.drop("geometry")[:6])}
                          for c, g in capas.items()])
    fig, ax = plt.subplots(figsize=(9, 9))
    capas["Admin_MINAM_BAS_LIM_DISTRITOS"].boundary.plot(ax=ax, color="0.6", lw=0.5)
    capas["Footprints"].boundary.plot(ax=ax, color="orange", lw=1)
    capas["EMSN038_AOI"].boundary.plot(ax=ax, color="k", lw=1.5)
    capas["Potential_Maximum_flood"].plot(ax=ax, color="red", alpha=0.7)
    capas["Riverbank"].plot(ax=ax, color="blue", alpha=0.7)
    ax.set_title("EMSN038: AOI (negro), huellas (naranja), inundación potencial (rojo), riberas (azul), distritos (gris)", fontsize=9)
    ax.set_xlim(capas["EMSN038_AOI"].total_bounds[[0, 2]]); ax.set_ylim(capas["EMSN038_AOI"].total_bounds[[1, 3]])
    plt.show()
    return tabla


def mostrar_conida(max_lado=1400):
    """Los mapas CONIDA 2023 (imágenes) que se usan para la comparación visual."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    rutas = sorted((C.DATOS / "test_lima" / "conida_2023").iterdir())
    fig, ejes = plt.subplots(1, len(rutas), figsize=(5 * len(rutas), 5))
    tabla = []
    for ax, r in zip(np.atleast_1d(ejes), rutas):
        im = Image.open(r)
        tabla.append({"archivo": r.name, "tamaño": f"{im.size[0]}×{im.size[1]}", "modo": im.mode,
                      "MB": round(r.stat().st_size / 1e6, 1)})
        im.thumbnail((max_lado, max_lado))
        ax.imshow(im); ax.set_title(r.name, fontsize=8); ax.axis("off")
    plt.tight_layout()
    plt.show()
    return pd.DataFrame(tabla)
