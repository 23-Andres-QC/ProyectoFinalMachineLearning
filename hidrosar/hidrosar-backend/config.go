package main

import (
	"errors"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	BaseDatos      string
	SecretoJWT     []byte
	AdminNombre    string
	AdminEmail     string
	AdminClave     string
	ModeloURL      string
	Zona           *time.Location
	MaxAreaKm2     float64
	CookieSegura   bool
	DuracionSesion time.Duration
}

func valor(nombre, defecto string) string {
	if v := strings.TrimSpace(os.Getenv(nombre)); v != "" {
		return v
	}
	return defecto
}

func cargarConfig() (Config, error) {
	c := Config{
		BaseDatos:      valor("DATABASE_URL", ""),
		SecretoJWT:     []byte(valor("JWT_SECRET", "")),
		AdminNombre:    valor("ADMIN_NOMBRE", "Administrador"),
		AdminEmail:     normalizarEmail(valor("ADMIN_EMAIL", "")),
		AdminClave:     os.Getenv("ADMIN_PASSWORD"),
		ModeloURL:      strings.TrimRight(valor("MODELO_URL", "http://modelo:8000"), "/"),
		CookieSegura:   valor("COOKIE_SEGURA", "false") == "true",
		DuracionSesion: 12 * time.Hour,
	}
	if c.BaseDatos == "" {
		return c, errors.New("falta DATABASE_URL")
	}
	if len(c.SecretoJWT) < 32 {
		return c, errors.New("JWT_SECRET debe tener al menos 32 caracteres")
	}
	zona, err := time.LoadLocation(valor("ZONA_HORARIA", "America/Lima"))
	if err != nil {
		return c, err
	}
	c.Zona = zona
	c.MaxAreaKm2, err = strconv.ParseFloat(valor("MAX_AREA_KM2", "150"), 64)
	if err != nil || c.MaxAreaKm2 <= 0 {
		return c, errors.New("MAX_AREA_KM2 debe ser un número positivo")
	}
	return c, nil
}

func normalizarEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}
