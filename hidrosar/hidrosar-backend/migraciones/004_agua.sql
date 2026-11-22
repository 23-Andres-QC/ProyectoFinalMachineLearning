-- Toda el agua que segmenta el modelo el día de la lluvia (mar, ríos y charcos), aparte de los charcos de lluvia.
-- Queda NULL en las evaluaciones anteriores y con los modelos de cambio, que solo marcan el agua nueva.
ALTER TABLE evaluaciones ADD COLUMN IF NOT EXISTS agua geometry(MultiPolygon, 4326);
ALTER TABLE evaluaciones ADD COLUMN IF NOT EXISTS agua_total_m2 DOUBLE PRECISION;
