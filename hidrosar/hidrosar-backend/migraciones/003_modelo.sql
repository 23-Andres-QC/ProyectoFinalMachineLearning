-- Modelo elegido para cada evaluación (id del catálogo del servicio del modelo). Vacío = el predeterminado (MODELO_PT).
ALTER TABLE evaluaciones ADD COLUMN IF NOT EXISTS modelo TEXT NOT NULL DEFAULT '';
