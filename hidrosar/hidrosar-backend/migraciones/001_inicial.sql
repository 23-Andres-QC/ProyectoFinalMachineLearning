CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE usuarios (
    id            BIGSERIAL PRIMARY KEY,
    nombre        TEXT        NOT NULL,
    email         TEXT        NOT NULL UNIQUE,
    clave_hash    TEXT        NOT NULL,
    rol           TEXT        NOT NULL CHECK (rol IN ('administrador', 'evaluador')),
    activo        BOOLEAN     NOT NULL DEFAULT TRUE,
    creado        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ultimo_acceso TIMESTAMPTZ
);

-- Solo se guarda el resultado: el área evaluada, los datos de la pasada y los polígonos del agua de lluvia.
-- Las imágenes NISAR se procesan en memoria en el servicio del modelo y no se guardan.
CREATE TABLE evaluaciones (
    id             BIGSERIAL PRIMARY KEY,
    usuario_id     BIGINT      NOT NULL REFERENCES usuarios (id) ON DELETE CASCADE,
    area           geometry(Polygon, 4326) NOT NULL,
    fecha_lluvia   DATE        NOT NULL,
    pasada         JSONB       NOT NULL,
    referencias    JSONB       NOT NULL DEFAULT '[]',
    estado         TEXT        NOT NULL DEFAULT 'en_cola'
                   CHECK (estado IN ('en_cola', 'procesando', 'completado', 'error')),
    mensaje        TEXT        NOT NULL DEFAULT '',
    metodo         TEXT        NOT NULL DEFAULT '',
    charcos        INTEGER,
    area_agua_m2   DOUBLE PRECISION,
    mb_descargados DOUBLE PRECISION,
    resultado      geometry(MultiPolygon, 4326),
    creado         TIMESTAMPTZ NOT NULL DEFAULT now(),
    iniciado       TIMESTAMPTZ,
    terminado      TIMESTAMPTZ
);

CREATE INDEX evaluaciones_usuario ON evaluaciones (usuario_id, creado DESC);
CREATE INDEX evaluaciones_pendientes ON evaluaciones (creado) WHERE estado IN ('en_cola', 'procesando');
CREATE INDEX evaluaciones_area ON evaluaciones USING GIST (area);
