-- Validaciones de los modelos entrenados en las escenas de validación de los notebooks: una fila por escena y modelo.
-- Solo se guardan los polígonos de aciertos, falsas alarmas y omisiones; las imágenes se procesan en memoria.
CREATE TABLE validaciones (
    id         BIGSERIAL PRIMARY KEY,
    escena     TEXT        NOT NULL,
    modelo     TEXT        NOT NULL,
    estado     TEXT        NOT NULL DEFAULT 'pendiente'
               CHECK (estado IN ('pendiente', 'procesando', 'completado', 'error')),
    mensaje    TEXT        NOT NULL DEFAULT '',
    intentos   INT         NOT NULL DEFAULT 0,
    referencia TEXT        NOT NULL DEFAULT '',
    area       geometry(Polygon, 4326) NOT NULL,
    aciertos   geometry(MultiPolygon, 4326),
    falsas     geometry(MultiPolygon, 4326),
    omisiones  geometry(MultiPolygon, 4326),
    segundos   DOUBLE PRECISION,
    creado     TIMESTAMPTZ NOT NULL DEFAULT now(),
    iniciado   TIMESTAMPTZ,
    terminado  TIMESTAMPTZ,
    UNIQUE (escena, modelo)
);

CREATE INDEX validaciones_pendientes ON validaciones (escena, modelo) WHERE estado IN ('pendiente', 'procesando');
