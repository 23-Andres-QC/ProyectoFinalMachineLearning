-- Pasos del proceso (carga del modelo, relieve, descargas, segmentación, polígonos) con su estado, detalle y segundos.
-- Lo informa el servicio del modelo mientras procesa; queda guardado para ver dónde falló una evaluación.
ALTER TABLE evaluaciones ADD COLUMN IF NOT EXISTS progreso JSONB;
