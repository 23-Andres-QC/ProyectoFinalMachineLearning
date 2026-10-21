"""Dataset de parches, lotes balanceados, pérdida BCE+Dice enmascarada, métricas y bucle de entrenamiento."""
import random
from pathlib import Path

import numpy as np, pandas as pd, torch
import segmentation_models_pytorch as smp
from torch.utils.data import Dataset, DataLoader, Sampler
from tqdm.auto import tqdm

from . import config as C


def normalizar(img, validos, stats, canales):
    """img (4|C, H, W) en dB -> canales elegidos normalizados; los inválidos quedan en 0 (= media)."""
    media = np.array(stats["media"], "float32")[canales, None, None]
    std = np.array(stats["std"], "float32")[canales, None, None]
    x = np.nan_to_num(img, nan=C.DB_MIN).astype("float32", copy=True)
    np.clip(x, C.DB_MIN, C.DB_MAX, out=x)
    x -= media
    x /= std
    x[:, ~validos] = 0
    return x


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
    """Parches que la evaluación de calidad aprobó para el modo (columna `agua` / `cambio` del índice)."""
    df = indice[indice[modo]]
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
    c, total, n = np.zeros(4), 0.0, 0
    with torch.no_grad(), torch.autocast(dispositivo, enabled=dispositivo == "cuda"):
        for img, lab, v in cargador:
            img, lab, v = img.to(dispositivo), lab.to(dispositivo), v.to(dispositivo)
            logits = modelo(img).float()
            total += perdida(logits, lab, v).item() * len(img)
            n += len(img)
            p, l, m = torch.sigmoid(logits) >= umbral, lab > 0.5, v > 0.5
            c += [(p & l & m).sum().item(), (p & ~l & m).sum().item(), (~p & l & m).sum().item(), (~p & ~l & m).sum().item()]
    return {"perdida_val": total / max(n, 1), **metricas(*c)}


# ---------------------------------------------------------------- carga con GPU
# Los .npz comprimidos se empaquetan una vez en arreglos .npy sin comprimir (memmap).
# Así no hacen falta procesos auxiliares (cada uno carga torch y ~0.6 GB de RAM en Windows):
# la CPU solo lee bytes del disco y la normalización y los aumentos se hacen en la GPU.

def empaquetar(indice, carpeta=C.PREPARADO / "empaquetado"):
    """Crea (una vez) img (N,4,T,T) float16, lab/val/val_pre (N,T,T) uint8. Devuelve {ruta: posición}."""
    carpeta = Path(carpeta)
    lista = carpeta / "rutas.csv"
    if lista.exists():
        rutas = pd.read_csv(lista).ruta.tolist()
        if set(rutas) >= set(indice.ruta):
            return carpeta, {r: k for k, r in enumerate(rutas)}
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas, N = indice.ruta.tolist(), len(indice)
    arr = {"img": np.lib.format.open_memmap(carpeta / "img.npy", "w+", "float16", (N, 4, C.T, C.T))}
    for k in ["lab", "val", "val_pre"]:
        arr[k] = np.lib.format.open_memmap(carpeta / f"{k}.npy", "w+", "uint8", (N, C.T, C.T))
    for i, r in enumerate(tqdm(rutas, desc="empaquetando")):
        with np.load(r) as d:
            for k in arr:
                arr[k][i] = d[k]
        if i % 500 == 499:              # vacía a disco para no acumular páginas en RAM
            for a in arr.values():
                a.flush()
    for a in arr.values():
        a.flush()
    del arr
    pd.DataFrame({"ruta": rutas}).to_csv(lista, index=False)
    return carpeta, {r: k for k, r in enumerate(rutas)}


class _ArchivoNpy:
    """Lee filas sueltas de un .npy grande sin mapearlo en memoria."""
    def __init__(self, ruta):
        self.f = open(ruta, "rb")
        version = np.lib.format.read_magic(self.f)
        leer_cab = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
        self.forma, _, self.dtype = leer_cab(self.f)
        self.inicio = self.f.tell()
        self.fila = int(np.prod(self.forma[1:])) * self.dtype.itemsize

    def leer(self, filas):
        out = np.empty((len(filas),) + tuple(self.forma[1:]), self.dtype)
        for k, i in enumerate(filas):
            self.f.seek(self.inicio + int(i) * self.fila)
            self.f.readinto(memoryview(out[k]).cast("B"))
        return out


class CargadorGPU:
    """Itera lotes (x, y, m) ya en la GPU. `lotes` (p. ej. LotesBalanceados) da índices sobre `posiciones`;
    sin `lotes` recorre todo en orden (validación)."""
    def __init__(self, carpeta, posiciones, modo, stats, dispositivo, aumentar, lotes=None, lote=C.LOTE):
        # Lectura con read() y no memmap: lo leído queda en la caché de Windows (memoria disponible)
        # en lugar de sumarse a la memoria del proceso.
        self.arch = {k: _ArchivoNpy(Path(carpeta) / f"{k}.npy") for k in ["img", "lab", "val", "val_pre"]}
        self.pos, self.cfg, self.disp, self.aumentar = np.asarray(posiciones), C.MODOS[modo], dispositivo, aumentar
        self.lotes, self.lote = lotes, lote
        cn = self.cfg["canales"]
        self.media = torch.tensor(stats["media"], device=dispositivo)[cn].view(1, -1, 1, 1)
        self.std = torch.tensor(stats["std"], device=dispositivo)[cn].view(1, -1, 1, 1)
        self.positivas = torch.tensor(self.cfg["positivas"], device=dispositivo)

    def __len__(self):
        return len(self.lotes) if self.lotes is not None else -(-len(self.pos) // self.lote)

    def _lote(self, idx):
        idx = np.sort(self.pos[idx])                     # lectura secuencial del disco
        t = lambda a: torch.from_numpy(np.ascontiguousarray(a)).to(self.disp, non_blocking=True)
        x = t(self.arch["img"].leer(idx)[:, self.cfg["canales"]]).float()
        lab, m = t(self.arch["lab"].leer(idx)), t(self.arch["val"].leer(idx))
        if self.cfg["requiere_pre"]:
            m = m & t(self.arch["val_pre"].leer(idx))
        x = (torch.nan_to_num(x, nan=C.DB_MIN).clamp_(C.DB_MIN, C.DB_MAX) - self.media) / self.std
        m = m.bool().unsqueeze(1)
        x = x * m
        y = torch.isin(lab, self.positivas).unsqueeze(1).float()
        m = m.float()
        if self.aumentar:
            for b in range(len(x)):
                g, f = int(torch.randint(4, ())), bool(torch.rand(()) < 0.5)
                for a in (x, y, m):
                    a[b] = torch.rot90(a[b], g, dims=(1, 2))
                    if f:
                        a[b] = torch.flip(a[b], dims=(2,))
        return x, y, m

    def __iter__(self):
        lotes = self.lotes if self.lotes is not None else \
            [list(range(i, min(i + self.lote, len(self.pos)))) for i in range(0, len(self.pos), self.lote)]
        for idx in lotes:
            yield self._lote(np.asarray(idx))


def _log(texto, archivo=C.RESULTADOS / "entrenamiento.log"):
    print(texto, flush=True)
    with open(archivo, "a", encoding="utf-8") as f:
        f.write(texto + "\n")


def entrenar(encoder, modo, train, val, stats, dispositivo, salida=C.RESULTADOS / "modelos", log=_log):
    """Entrena una U-Net y guarda el mejor estado según IoU de validación. Devuelve (mejor, historial)."""
    salida.mkdir(parents=True, exist_ok=True)
    fijar_semilla()
    if dispositivo == "cuda":
        carpeta, pos = empaquetar(pd.concat([train, val]))
        cargador_train = CargadorGPU(carpeta, train.ruta.map(pos), modo, stats, dispositivo, aumentar=True,
                                     lotes=LotesBalanceados(np.flatnonzero(train.positivo), len(train), C.LOTE))
        cargador_val = CargadorGPU(carpeta, val.ruta.map(pos), modo, stats, dispositivo, aumentar=False)
    else:
        kw = dict(num_workers=C.NUM_WORKERS, persistent_workers=C.NUM_WORKERS > 0)
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
            if not torch.isfinite(l):        # evita que un desborde de fp16 arruine los pesos (visto con VGG19)
                continue
            escalador.scale(l).backward()
            escalador.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(modelo.parameters(), 1.0)
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
