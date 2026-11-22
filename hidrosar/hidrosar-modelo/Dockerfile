FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
# PyTorch y torchvision de CPU (sin las librerías de CUDA, ~1.5 GB menos); smp y timm los reutilizan
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY requirements.txt .
RUN pip install -r requirements.txt
# Grilla del geoide EGM2008 dentro de la imagen. Sin ella, PROJ la baja de la red en cada contenedor nuevo, y si la descarga
# falla devuelve infinito: el DEM queda inservible y el área parece fuera de la franja del radar.
RUN python -c "import pyproj, urllib.request; urllib.request.urlretrieve('https://cdn.proj.org/us_nga_egm08_25.tif', pyproj.datadir.get_data_dir() + '/us_nga_egm08_25.tif')"
# rasterio (GDAL) necesita libexpat, que ya no viene en la imagen slim
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY *.py ./
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
