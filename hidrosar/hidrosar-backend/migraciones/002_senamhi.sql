-- Lluvia medida por las estaciones automáticas del Senamhi, cargada desde las tablas horarias que exporta su portal.
CREATE TABLE estaciones_senamhi (
    codigo       TEXT PRIMARY KEY,
    nombre       TEXT             NOT NULL,
    departamento TEXT             NOT NULL DEFAULT '',
    provincia    TEXT             NOT NULL DEFAULT '',
    distrito     TEXT             NOT NULL DEFAULT '',
    lat          DOUBLE PRECISION NOT NULL,
    lon          DOUBLE PRECISION NOT NULL,
    altitud_m    DOUBLE PRECISION,
    tipo         TEXT             NOT NULL DEFAULT ''
);

-- Una fila por estación y hora, en hora local del Perú (UTC-5) tal como la publica el Senamhi.
-- mm NULL = "S/D" (sin dato) en la tabla original.
CREATE TABLE lluvia_senamhi (
    estacion TEXT      NOT NULL REFERENCES estaciones_senamhi (codigo) ON DELETE CASCADE,
    hora     TIMESTAMP NOT NULL,
    mm       REAL,
    PRIMARY KEY (estacion, hora)
);

CREATE INDEX lluvia_senamhi_hora ON lluvia_senamhi (hora);
