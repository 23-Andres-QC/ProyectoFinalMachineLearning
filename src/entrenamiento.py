"""Dataset de parches, lotes balanceados, pérdida BCE+Dice enmascarada, métricas y bucle de entrenamiento."""
import random

import numpy as np, pandas as pd, torch
import segmentation_models_pytorch as smp
from torch.utils.data import Dataset, DataLoader, Sampler

from . import config as C


def normalizar(img, validos, stats, canales):
    """img (4|C, H, W) en dB -> canales elegidos normalizados; los inválidos quedan en 0 (= media)."""
    media = np.array(stats["media"], "float32")[canales, None, None]
    std = np.array(stats["std"], "float32")[canales, None, None]
    x = (np.clip(np.nan_to_num(img, nan=C.DB_MIN), C.DB_MIN, C.DB_MAX) - media) / std
    return np.where(validos[None], x, 0).astype("float32")


class Parches(Dataset):
    def __init__(self, indice, modo, stats, aumentar):
        self.rutas = indice.ruta.tolist()
        self.cfg, self.stats, self.aumentar = C.MODOS[modo], stats, aumentar

    def __len__(self):
        return len(self.rutas)

    def __getitem__(self, k):
        d = np.load(self.rutas[k])
        m = d["val"] & d["val_pre"] if self.cfg["requiere_pre"] else d["val"]
        img = d["img"][self.cfg["canales"]].astype("float32")
        arr = [normalizar(img, m == 1, self.stats, self.cfg["canales"]),
               np.isin(d["lab"], self.cfg["positivas"])[None].astype("float32"),
               m[None].astype("float32")]
        if self.aumentar:
            g = int(torch.randint(4, ()))
            arr = [np.rot90(a, g, axes=(1, 2)) for a in arr]
            if torch.rand(()) < 0.5:
                arr = [a[:, :, ::-1] for a in arr]
        return tuple(torch.from_numpy(np.ascontiguousarray(a)) for a in arr)


class LotesBalanceados(Sampler):
    """La mitad de cada lote contiene parches con clase positiva (como Paul y Ganju, 2021)."""
    def __init__(self, positivos, n_total, lote, semilla=C.SEMILLA):
        self.positivos, self.n_total, self.lote = list(positivos), n_total, lote
        self.rng = random.Random(semilla)

    def __len__(self):
        return max(self.n_total // self.lote, 1)

    def __iter__(self):
        mitad = self.lote // 2
        for _ in range(len(self)):
            yield self.rng.choices(self.positivos, k=mitad) + self.rng.sample(range(self.n_total), self.lote - mitad)


def filtrar(indice, modo):
    """Parches utilizables por el modo; en 'cambio' solo los que tienen imagen previa."""
    cfg = C.MODOS[modo]
    df = indice[indice.tiene_pre] if cfg["requiere_pre"] else indice
    col = "frac_inundacion" if modo == "cambio" else "frac_agua"
    df = df.assign(positivo=df[col] > C.FRAC_AGUA_POSITIVO)
    return df.query("particion == 'train'").reset_index(drop=True), df.query("particion == 'val'").reset_index(drop=True)


def perdida(logits, lab, val):
    p = torch.sigmoid(logits)
    bce = torch.nn.functional.binary_cross_entropy_with_logits(logits, lab, reduction="none")
    bce = (bce * val).sum() / val.sum().clamp(min=1)
    inter = (p * lab * val).sum()
    dice = 1 - (2 * inter + 1) / (((p + lab) * val).sum() + 1)
    return bce + dice


def metricas(tp, fp, fn, tn):
    return {"IoU": tp / max(tp + fp + fn, 1), "Dice": 2 * tp / max(2 * tp + fp + fn, 1),
            "Precision": tp / max(tp + fp, 1), "Recall": tp / max(tp + fn, 1),
            "Accuracy": (tp + tn) / max(tp + fp + fn + tn, 1)}


def conteos(pred, ref):
    """pred, ref: arrays booleanos ya restringidos a píxeles válidos."""
    return (pred & ref).sum(), (pred & ~ref).sum(), (~pred & ref).sum(), (~pred & ~ref).sum()


def crear_modelo(encoder, modo, pesos="imagenet"):
    return smp.Unet(encoder, encoder_weights=pesos, in_channels=len(C.MODOS[modo]["canales"]), classes=1)


def fijar_semilla(s=C.SEMILLA):
    random.seed(s); np.random.seed(s); torch.manual_seed(s)
    torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark = True, False


def evaluar(modelo, cargador, dispositivo, umbral=C.UMBRAL):
    modelo.eval()
    c, total = np.zeros(4), 0.0
    with torch.no_grad(), torch.autocast(dispositivo, enabled=dispositivo == "cuda"):
        for img, lab, v in cargador:
            img, lab, v = img.to(dispositivo), lab.to(dispositivo), v.to(dispositivo)
            logits = modelo(img).float()
            total += perdida(logits, lab, v).item() * len(img)
            p, l, m = torch.sigmoid(logits) >= umbral, lab > 0.5, v > 0.5
            c += [(p & l & m).sum().item(), (p & ~l & m).sum().item(), (~p & l & m).sum().item(), (~p & ~l & m).sum().item()]
    return {"perdida_val": total / len(cargador.dataset), **metricas(*c)}


def _log(texto, archivo=C.SALIDA / "entrenamiento.log"):
    print(texto, flush=True)
    with open(archivo, "a", encoding="utf-8") as f:
        f.write(texto + "\n")


def entrenar(encoder, modo, train, val, stats, dispositivo, salida=C.SALIDA / "modelos", log=_log):
    """Entrena una U-Net y guarda el mejor estado según IoU de validación. Devuelve (mejor, historial)."""
    salida.mkdir(parents=True, exist_ok=True)
    fijar_semilla()
    kw = dict(num_workers=C.NUM_WORKERS, persistent_workers=C.NUM_WORKERS > 0, pin_memory=dispositivo == "cuda")
    cargador_train = DataLoader(Parches(train, modo, stats, aumentar=True),
                                batch_sampler=LotesBalanceados(np.flatnonzero(train.positivo), len(train), C.LOTE), **kw)
    cargador_val = DataLoader(Parches(val, modo, stats, aumentar=False), batch_size=C.LOTE, shuffle=False, **kw)

    modelo = crear_modelo(encoder, modo).to(dispositivo)
    opt = torch.optim.AdamW(modelo.parameters(), lr=C.LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, mode="max", factor=0.5, patience=2)
    escalador = torch.amp.GradScaler(enabled=dispositivo == "cuda")
    ruta = salida / f"unet_{modo}_{encoder}.pt"
    mejor, sin_mejora, historial = None, 0, []
    for epoca in range(1, C.MAX_EPOCAS + 1):
        modelo.train()
        suma = 0.0
        for img, lab, v in cargador_train:
            img, lab, v = img.to(dispositivo), lab.to(dispositivo), v.to(dispositivo)
            opt.zero_grad(set_to_none=True)
            with torch.autocast(dispositivo, enabled=dispositivo == "cuda"):
                logits = modelo(img)
            l = perdida(logits.float(), lab, v)
            escalador.scale(l).backward()
            escalador.step(opt)
            escalador.update()
            suma += l.item()
        m = evaluar(modelo, cargador_val, dispositivo)
        sched.step(m["IoU"])
        fila = {"modo": modo, "encoder": encoder, "epoca": epoca, "lr": opt.param_groups[0]["lr"],
                "perdida_train": suma / len(cargador_train), **m}
        historial.append(fila)
        log(f"{modo:6s} {encoder:16s} época {epoca:2d} · train {fila['perdida_train']:.3f} · "
            f"val {m['perdida_val']:.3f} · IoU {m['IoU']:.3f} · F1 {m['Dice']:.3f}")
        if mejor is None or m["IoU"] > mejor["IoU"]:
            mejor, sin_mejora = {k: v for k, v in fila.items() if k not in ("lr", "perdida_train")}, 0
            torch.save(modelo.state_dict(), ruta)
        else:
            sin_mejora += 1
            if sin_mejora >= C.PACIENCIA:
                break
    return mejor, pd.DataFrame(historial)
