package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type App struct {
	cfg           Config
	db            *pgxpool.Pool
	cliente       *http.Client
	clienteModelo *http.Client
	busquedas     *cacheBusquedas
	cacheLluvia   *cacheTTL[[]diaLluvia]
	cacheASF      *cacheTTL[[]granulo]
	cacheCatalogo *cacheTTL[catalogoValidacion]
	limitador     *limitador
	aviso         chan struct{}
}

func nuevaApp(cfg Config, db *pgxpool.Pool) *App {
	return &App{
		cfg:           cfg,
		db:            db,
		cliente:       &http.Client{Timeout: 90 * time.Second},
		clienteModelo: &http.Client{Timeout: 2 * time.Hour},
		busquedas:     nuevaCache(time.Hour),
		cacheLluvia:   nuevaCacheTTL[[]diaLluvia](time.Hour),
		cacheASF:      nuevaCacheTTL[[]granulo](time.Hour),
		cacheCatalogo: nuevaCacheTTL[catalogoValidacion](time.Minute),
		limitador:     nuevoLimitador(10, 5*time.Minute),
		aviso:         make(chan struct{}, 1),
	}
}

func (a *App) rutas() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("GET /api/salud", a.salud)
	m.HandleFunc("POST /api/auth/login", a.login)
	m.HandleFunc("POST /api/auth/logout", a.logout)
	m.Handle("GET /api/auth/yo", a.conSesion(a.yo))
	m.Handle("PUT /api/auth/clave", a.conSesion(a.cambiarClave))

	m.Handle("GET /api/usuarios", a.soloAdmin(a.listarUsuarios))
	m.Handle("POST /api/usuarios", a.soloAdmin(a.crearUsuario))
	m.Handle("PUT /api/usuarios/{id}", a.soloAdmin(a.editarUsuario))
	m.Handle("DELETE /api/usuarios/{id}", a.soloAdmin(a.eliminarUsuario))

	m.Handle("POST /api/nisar/buscar", a.conSesion(a.buscarNisar))
	m.Handle("GET /api/lluvias/regiones", a.conSesion(a.listarRegiones))
	m.Handle("GET /api/lluvias", a.conSesion(a.listarLluvias))
	m.Handle("GET /api/lluvias/senamhi", a.conSesion(a.listarLluviasSenamhi))
	m.Handle("GET /api/lluvias/senamhi/estaciones", a.conSesion(a.listarEstacionesSenamhi))
	m.Handle("POST /api/lluvias/senamhi/tablas", a.soloAdmin(a.subirSenamhi))

	m.Handle("GET /api/historial", a.conSesion(a.listarHistorial))
	m.Handle("GET /api/evaluaciones", a.conSesion(a.listarEvaluaciones))
	m.Handle("POST /api/evaluaciones", a.conSesion(a.crearEvaluacion))
	m.Handle("GET /api/evaluaciones/{id}", a.conSesion(a.verEvaluacion))
	m.Handle("GET /api/evaluaciones/{id}/resultado.geojson", a.conSesion(a.descargarGeoJSON))
	m.Handle("GET /api/evaluaciones/{id}/resultado.kml", a.conSesion(a.descargarKML))
	m.Handle("GET /api/evaluaciones/{id}/agua", a.conSesion(a.verAgua))
	m.Handle("POST /api/evaluaciones/{id}/reintentar", a.conSesion(a.reintentarEvaluacion))
	m.Handle("DELETE /api/evaluaciones/{id}", a.conSesion(a.eliminarEvaluacion))

	m.Handle("GET /api/validaciones", a.conSesion(a.listarValidaciones))
	m.Handle("GET /api/validaciones/{id}", a.conSesion(a.verValidacion))
	m.Handle("POST /api/validaciones/{id}/recalcular", a.soloAdmin(a.recalcularValidacion))
	return registrar(m)
}

func (a *App) salud(w http.ResponseWriter, r *http.Request) {
	estado := map[string]any{
		"backend":      "ok",
		"max_area_km2": a.cfg.MaxAreaKm2,
		"zona_horaria": a.cfg.Zona.String(),
	}
	ctx, listo := context.WithTimeout(r.Context(), 3*time.Second)
	defer listo()
	modelo := map[string]any{"disponible": false}
	if req, err := http.NewRequestWithContext(ctx, http.MethodGet, a.cfg.ModeloURL+"/salud", nil); err == nil {
		if resp, err := a.cliente.Do(req); err == nil {
			defer resp.Body.Close()
			if json.NewDecoder(resp.Body).Decode(&modelo) != nil {
				modelo = map[string]any{"disponible": false}
			}
		}
	}
	estado["modelo"] = modelo
	responderJSON(w, http.StatusOK, estado)
}

func (a *App) errorInterno(w http.ResponseWriter, err error) {
	log.Printf("error interno: %v", err)
	responderError(w, http.StatusInternalServerError, "Error interno del servidor")
}
