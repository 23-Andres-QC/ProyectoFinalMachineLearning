"""Aplica un modelo entrenado a un GeoTIFF Sentinel-1 (VV, VH en dB) y guarda probabilidad, máscara y figura.

Ejemplos:
    python predecir_tif.py Data/test_lima/procesadas/lima_2023_0316.tif --modo agua
    python predecir_tif.py Data/test_lima/procesadas/lima_2023_0316.tif --modo cambio \
        --pre Data/test_lima/procesadas/lima_2023_0304.tif --hand
"""
import argparse
from pathlib import Path

import numpy as np, pandas as pd, rasterio, torch
import matplotlib.pyplot as plt

from src import config as C
from src import inferencia as I
from src.entrenamiento import metricas, conteos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tif")
    ap.add_argument("--pre", default=None, help="imagen previa (obligatoria en modo cambio)")
    ap.add_argument("--modo", choices=list(C.MODOS), default="agua")
    ap.add_argument("--vv", type=int, default=1)
    ap.add_argument("--vh", type=int, default=2)
    ap.add_argument("--lineal", action="store_true", help="la entrada está en potencia lineal")
    ap.add_argument("--encoder", default=None, help="por defecto, el mejor de resultados_val.csv")
    ap.add_argument("--umbral", type=float, default=C.UMBRAL)
    ap.add_argument("--hand", action="store_true", help=f"descarta píxeles con HAND >= {C.HAND_MAX} m")
    ap.add_argument("--referencia", default=None, help="GeoTIFF con -1 inválido, 0 sin agua, 1 agua")
    ap.add_argument("--salida", default=str(C.SALIDA / "predicciones"))
    a = ap.parse_args()

    if a.modo == "cambio" and a.pre is None:
        ap.error("el modo cambio necesita --pre")
    dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
    encoder = a.encoder or pd.read_csv(C.SALIDA / "resultados_val.csv").query("modo == @a.modo").sort_values("IoU").encoder.iloc[-1]
    modelo, stats = I.cargar_modelo(a.modo, encoder, dispositivo), I.cargar_stats()

    post, perfil = I.leer_escena(a.tif, (a.vv, a.vh), a.lineal)
    pre = I.leer_en_grilla(a.pre, perfil, (a.vv, a.vh)) if a.pre else None
    if pre is not None and a.lineal:
        pre = 10 * np.log10(np.clip(pre, 1e-6, None))
    prob, valido = I.probabilidad(modelo, a.modo, stats, post, pre, dispositivo)
    agua = (prob >= a.umbral) & valido
    if a.hand:
        agua &= I.a_grilla(C.HAND, perfil) < C.HAND_MAX

    nombre = f"{Path(a.tif).stem}_{a.modo}"
    salida = Path(a.salida)
    I.guardar_tif(salida / f"{nombre}_mascara.tif", np.where(valido, agua, 255), perfil, "uint8", 255)
    I.guardar_tif(salida / f"{nombre}_prob.tif", np.where(valido, prob, -1), perfil, "float32", -1)
    pct = 100 * agua[valido].mean()
    print(f"unet_{a.modo}_{encoder} · píxeles válidos {valido.sum():,} · detectado {pct:.2f} %")

    paneles = [(np.ma.masked_where(~valido, post[1]), "VH (dB)", "gray", -25, 0),
               (np.ma.masked_where(~valido, prob), "probabilidad", "viridis", 0, 1),
               (np.ma.masked_where(~valido, agua), f"máscara (umbral {a.umbral})", "Blues", 0, 1)]
    if a.referencia:
        ref = rasterio.open(a.referencia).read(1)
        m = valido & (ref != -1)
        r = metricas(*conteos(agua[m], ref[m] == 1))
        print(" · ".join(f"{k} {v:.3f}" for k, v in r.items()))
        paneles.append((np.ma.masked_where(ref == -1, ref == 1), "referencia", "Blues", 0, 1))

    fig, ejes = plt.subplots(1, len(paneles), figsize=(4.5 * len(paneles), 4.5))
    for ax, (z, t, cmap, vmin, vmax) in zip(ejes, paneles):
        k = max(1, max(z.shape) // 1500)
        ax.imshow(z[::k, ::k], cmap=cmap, vmin=vmin, vmax=vmax)
        ax.set_title(t); ax.axis("off")
    fig.suptitle(f"{nombre} · unet_{a.modo}_{encoder} · {pct:.1f} %")
    plt.tight_layout()
    plt.savefig(salida / f"{nombre}.png", dpi=110)
    print(f"Guardado en {salida}/")


if __name__ == "__main__":
    main()
