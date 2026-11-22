import logging
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from errores import ErrorProceso
from procesamiento import Procesador
from progreso import Avance, avance_de

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
PREFIJO_NISAR = "https://nisar.asf.earthdatacloud.nasa.gov/"

app = FastAPI(title="HidroSAR · modelo")
procesador = Procesador()
candado = threading.Lock()


class Pedido(BaseModel):
    id: int
    bbox: list[float] = Field(min_length=4, max_length=4)
    lluvia: list[str] = Field(min_length=1)
    referencias: list[list[str]] = Field(default_factory=list)
    modelo: str = Field(default="", max_length=120)


@app.get("/salud")
def salud():
    return procesador.estado()


@app.get("/progreso/{id_}")
def progreso(id_: int):
    """Pasos de la evaluación (hecho, en curso, pendiente o con error); el backend lo consulta mientras procesa."""
    foto = avance_de(id_)
    if foto is None:
        raise HTTPException(404, "No hay avance de esa evaluación")
    return foto


@app.post("/procesar")
def procesar(pedido: Pedido):
    urls = pedido.lluvia + [u for r in pedido.referencias for u in r]
    if any(not u.startswith(PREFIJO_NISAR) or not u.endswith(".h5") for u in urls):
        raise HTTPException(400, "Solo se aceptan archivos RSLC de NISAR en ASF")
    with candado:
        logging.info("evaluación %s: inicio (%d cuadro(s), %d referencia(s), modelo %s)", pedido.id, len(pedido.lluvia),
                     len(pedido.referencias), pedido.modelo or procesador.predeterminado)
        avance = Avance(pedido.id)
        try:
            resultado = procesador.procesar(pedido.bbox, pedido.lluvia, pedido.referencias, pedido.modelo, avance)
        except ErrorProceso as e:
            avance.fallar()
            logging.warning("evaluación %s: %s", pedido.id, e)
            raise HTTPException(422, str(e)) from e
        except Exception as e:
            avance.fallar()
            logging.exception("evaluación %s falló", pedido.id)
            raise HTTPException(500, f"Error al procesar: {e}") from e
    logging.info("evaluación %s: %d charcos, %.1f MB descargados, %.0f s", pedido.id, resultado["charcos"],
                 resultado["mb_descargados"], resultado["segundos"])
    return resultado
