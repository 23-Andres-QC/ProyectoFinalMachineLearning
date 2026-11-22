# HidroSAR

Web para detectar el agua de lluvia empozada en un área del mapa con radar NISAR y la U-Net entrenada en el notebook 01.
Cómo funciona por dentro: [LOGICA.md](LOGICA.md).

## Arrancar

1. Abre Docker Desktop.
2. Revisa `hidrosar/.env`. Si no existe, copia `.env.example` como `.env` y completa los valores.
   - Pon tu cuenta gratuita de NASA Earthdata en `EARTHDATA_USER` y `EARTHDATA_PASSWORD`.
3. Copia en `hidrosar-modelo/modelos/` dos archivos de Kaggle:
   - el modelo entrenado, que es el `.pt` que indica `MODELO_PT` en el `.env`;
   - `umbrales.json`.
4. Dentro de `hidrosar/`, ejecuta:

   ```
   docker compose up -d --build
   ```

5. Abre http://localhost:8080 e ingresa con `ADMIN_EMAIL` y `ADMIN_PASSWORD` del `.env`.
   - Esos datos solo se usan la primera vez que arranca, para crear el administrador.
   - Después, la contraseña se cambia desde la web (botón *Contraseña*).

## Contenedores

| Contenedor | Imagen | Puerto |
|---|---|---|
| hidrosar-web | Vue + nginx | 8080 (el único expuesto) |
| hidrosar-backend | Go | interno 8080 |
| hidrosar-modelo | Python + PyTorch CPU | interno 8000 |
| hidrosar-db | PostgreSQL 17 + PostGIS | interno 5432 (volumen `hidrosar-db`) |

## Comandos útiles

| Para | Comando |
|---|---|
| Ver el estado | `docker compose ps` |
| Ver qué está procesando | `docker compose logs -f backend modelo` |
| Usar un `.pt` nuevo | `docker compose restart modelo` |
| Aplicar cambios del `.env` | `docker compose up -d` |
| Apagar todo (los datos se conservan) | `docker compose down` |
| Apagar y **borrar** la base de datos | `docker compose down -v` |

## Historial

Todo lo procesado queda guardado en PostgreSQL, en el volumen `hidrosar-db`. Cada vez que entras al mapa, el historial se dibuja solo.

- Se conserva si apagas los contenedores, reinicias la PC o reconstruyes las imágenes.
- Solo se borra con `docker compose down -v` o si eliminas la evaluación desde la web.
- Para guardar una copia, ejecuta esto dentro de `hidrosar/`. Pesa unos pocos KB por evaluación.

  ```
  docker exec hidrosar-db pg_dump -U hidrosar --clean --if-exists -f /tmp/respaldo.sql hidrosar
  docker cp hidrosar-db:/tmp/respaldo.sql respaldo.sql
  ```

- Para restaurarla, ejecuta lo siguiente. Reemplaza lo que haya en la base por la copia.

  ```
  docker cp respaldo.sql hidrosar-db:/tmp/respaldo.sql
  docker exec hidrosar-db psql -U hidrosar -d hidrosar -f /tmp/respaldo.sql
  ```
