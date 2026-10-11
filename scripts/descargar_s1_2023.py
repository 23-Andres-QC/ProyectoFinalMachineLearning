import os, sys, time
import asf_search as asf

DEST = "test_lima/sentinel1_2023"
LIMA_SUR = "POLYGON((-77.0 -12.35,-76.75 -12.35,-76.75 -12.05,-77.0 -12.05,-77.0 -12.35))"

os.makedirs(DEST, exist_ok=True)
sesion = asf.ASFSession().auth_with_creds(os.environ["ED_USER"], os.environ["ED_PASS"])
res = asf.geo_search(platform=asf.PLATFORM.SENTINEL1, processingLevel=["GRD_HD", "GRD_HS"],
                     intersectsWith=LIMA_SUR, start="2023-02-15", end="2023-03-31")
res = sorted(res, key=lambda x: x.properties["startTime"])
total = sum(p.properties["bytes"] for p in res)
print(f"{len(res)} escenas, {total/1e9:.2f} GB", flush=True)

inicio = time.time()
for i, p in enumerate(res, 1):
    url, nombre, size = p.properties["url"], p.properties["fileName"], p.properties["bytes"]
    ruta = os.path.join(DEST, nombre)
    for intento in range(1, 11):
        ya = os.path.getsize(ruta) if os.path.exists(ruta) else 0
        if ya == size:
            break
        try:
            with sesion.get(url, headers={"Range": f"bytes={ya}-"} if ya else {},
                            stream=True, timeout=120) as r:
                r.raise_for_status()
                if ya and r.status_code != 206:
                    ya = 0
                with open(ruta, "ab" if ya else "wb") as f:
                    for trozo in r.iter_content(1024 * 1024):
                        f.write(trozo)
        except Exception as e:
            print(f"  [{nombre}] se cortó ({type(e).__name__}), reintento {intento}/10", flush=True)
            time.sleep(10)
    estado = "OK" if os.path.getsize(ruta) == size else "INCOMPLETO"
    print(f"[{i}/{len(res)}] {estado} {nombre} {size/1e9:.2f} GB "
          f"({(time.time()-inicio)/60:.1f} min)", flush=True)

print("FIN", flush=True)
