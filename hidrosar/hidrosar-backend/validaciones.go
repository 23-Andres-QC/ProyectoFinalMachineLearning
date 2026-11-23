package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
)

// Validaciones de los modelos entrenados: cada modelo del catálogo se corre en las escenas de validación de los notebooks
// (recortes NISAR ya guardados en el servicio del modelo) y se guardan tres capas para el mapa: aciertos, falsas alarmas
// y omisiones. Se calculan en segundo plano, después de las evaluaciones de los usuarios.

type escenaValidacion struct {
	Clave      string     `json:"clave"`
	Lugar      string     `json:"lugar"`
	Fecha      string     `json:"fecha"`
	Dia        string     `json:"dia"` // lluvia o seco
	Pista      string     `json:"pista"`
	Seco       *string    `json:"seco"`
	Origen     string     `json:"origen"`
	BBox       [4]float64 `json:"bbox"`
	Cambio     bool       `json:"cambio"` // tiene día seco de la misma órbita: sirve para los modelos de cambio
	Disponible bool       `json:"disponible"`
}

type modeloCatalogo struct {
	ID      string `json:"id"`
	Nombre  string `json:"nombre"`
	Familia string `json:"familia"`
	Tipo    string `json:"tipo"` // agua o cambio
}

type catalogoValidacion struct {
	Escenas []escenaValidacion `json:"escenas"`
	Modelos []modeloCatalogo   `json:"modelos"`
}

type ResumenValidacion struct {
	ID        int64      `json:"id"`
	Escena    string     `json:"escena"`
	Modelo    string     `json:"modelo"`
	Estado    string     `json:"estado"`
	Mensaje   string     `json:"mensaje"`
	Terminado *time.Time `json:"terminado"`
}

type respuestaValidacion struct {
	Aciertos   json.RawMessage `json:"aciertos"`
	Falsas     json.RawMessage `json:"falsas"`
	Omisiones  json.RawMessage `json:"omisiones"`
	Referencia string          `json:"referencia"`
	Segundos   float64         `json:"segundos"`
	Detalle    json.RawMessage `json:"detail"`
}

var errModeloCaido = errors.New("El servicio del modelo no responde")

const maxIntentosValidacion = 3

// pedirModelo: GET al servicio del modelo con un tiempo corto, para listar escenas y modelos.
func (a *App) pedirModelo(ctx context.Context, ruta string, v any) error {
	ctx, listo := context.WithTimeout(ctx, 5*time.Second)
	defer listo()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, a.cfg.ModeloURL+ruta, nil)
	if err != nil {
		return err
	}
	resp, err := a.cliente.Do(req)
	if err != nil {
		return errModeloCaido
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("El modelo respondió %s", resp.Status)
	}
	return json.NewDecoder(resp.Body).Decode(v)
}

// catalogo: escenas de validación y modelos que se validan (el mejor de cada grupo), del servicio del modelo. Se guarda
// un minuto.
func (a *App) catalogo(ctx context.Context) (catalogoValidacion, error) {
	if c, ok := a.cacheCatalogo.obtener("catalogo"); ok {
		return c, nil
	}
	var c catalogoValidacion
	if err := a.pedirModelo(ctx, "/validacion/escenas", &c.Escenas); err != nil {
		return c, err
	}
	if err := a.pedirModelo(ctx, "/validacion/modelos", &c.Modelos); err != nil {
		return c, err
	}
	a.cacheCatalogo.guardar("catalogo", c)
	return c, nil
}

// sincronizarValidaciones agrega como pendientes las validaciones que faltan: cada modelo que se valida en cada escena con
// sus recortes (los modelos de cambio, solo en las escenas con día seco). Las pendientes de otros modelos, que nunca se
// calcularon, salen de la cola. Devuelve los ids de los modelos que se validan.
func (a *App) sincronizarValidaciones(ctx context.Context) ([]string, error) {
	c, err := a.catalogo(ctx)
	if err != nil {
		return nil, err
	}
	var escenas, modelos []string
	var x0, y0, x1, y1 []float64
	ids := make([]string, 0, len(c.Modelos))
	for _, m := range c.Modelos {
		ids = append(ids, m.ID)
		for _, e := range c.Escenas {
			if !e.Disponible || (m.Tipo == "cambio" && !e.Cambio) {
				continue
			}
			escenas, modelos = append(escenas, e.Clave), append(modelos, m.ID)
			x0, y0, x1, y1 = append(x0, e.BBox[0]), append(y0, e.BBox[1]), append(x1, e.BBox[2]), append(y1, e.BBox[3])
		}
	}
	etiqueta, err := a.db.Exec(ctx, `
		INSERT INTO validaciones (escena, modelo, area)
		SELECT e, m, ST_MakeEnvelope(a, b, c, d, 4326)
		FROM unnest($1::text[], $2::text[], $3::float8[], $4::float8[], $5::float8[], $6::float8[]) t(e, m, a, b, c, d)
		ON CONFLICT (escena, modelo) DO NOTHING`, escenas, modelos, x0, y0, x1, y1)
	if err != nil {
		return nil, err
	}
	if n := etiqueta.RowsAffected(); n > 0 {
		log.Printf("validaciones: %d nuevas en cola", n)
	}
	if len(ids) > 0 {
		etiqueta, err = a.db.Exec(ctx, `DELETE FROM validaciones WHERE estado = 'pendiente' AND NOT (modelo = ANY($1))`, ids)
		if err != nil {
			return nil, err
		}
		if n := etiqueta.RowsAffected(); n > 0 {
			log.Printf("validaciones: %d pendientes de otros modelos salen de la cola", n)
		}
	}
	return ids, nil
}

// validarSiguiente corre una validación pendiente. Van en orden de escena para que el servicio reuse la zona ya
// preparada. Si el servicio está apagado (por ejemplo, mientras arranca) no se toma ninguna; si se cae a mitad de una,
// esa vuelve a quedar pendiente (hasta 3 intentos).
func (a *App) validarSiguiente(ctx context.Context, modelos []string) bool {
	var salud map[string]any
	if len(modelos) == 0 || a.pedirModelo(ctx, "/salud", &salud) != nil {
		return false
	}
	var id int64
	var escena, modelo string
	var intentos int
	err := a.db.QueryRow(ctx, `
		UPDATE validaciones SET estado = 'procesando', iniciado = now(), mensaje = '', intentos = intentos + 1
		WHERE id = (SELECT id FROM validaciones WHERE estado = 'pendiente' AND modelo = ANY($1)
		            ORDER BY escena, modelo LIMIT 1 FOR UPDATE SKIP LOCKED)
		RETURNING id, escena, modelo, intentos`, modelos).Scan(&id, &escena, &modelo, &intentos)
	if errors.Is(err, pgx.ErrNoRows) || ctx.Err() != nil {
		return false
	}
	if err != nil {
		log.Printf("validaciones: %v", err)
		return false
	}
	res, err := a.llamarValidacion(ctx, escena, modelo)
	if err != nil {
		if ctx.Err() != nil {
			return false
		}
		if errors.Is(err, errModeloCaido) && intentos < maxIntentosValidacion {
			if _, e := a.db.Exec(ctx, `UPDATE validaciones SET estado = 'pendiente', iniciado = NULL WHERE id = $1`, id); e != nil {
				log.Printf("validación %d: %v", id, e)
			}
			return false
		}
		log.Printf("validación %d (%s con %s): %v", id, escena, modelo, err)
		a.marcarErrorValidacion(ctx, id, err.Error())
		return true
	}
	_, err = a.db.Exec(ctx, `UPDATE validaciones SET estado = 'completado', referencia = $5, segundos = $6, terminado = now(),
		aciertos = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($2::text), 4326)), 3)),
		falsas = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($3::text), 4326)), 3)),
		omisiones = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($4::text), 4326)), 3))
		WHERE id = $1`, id, geoJSONONil(res.Aciertos), geoJSONONil(res.Falsas), geoJSONONil(res.Omisiones), res.Referencia, res.Segundos)
	if err != nil {
		log.Printf("validación %d: no se pudo guardar: %v", id, err)
		a.marcarErrorValidacion(ctx, id, "No se pudo guardar el resultado")
		return true
	}
	log.Printf("validación %d: %s con %s lista (%.0f s)", id, escena, modelo, res.Segundos)
	return true
}

func (a *App) llamarValidacion(ctx context.Context, escena, modelo string) (*respuestaValidacion, error) {
	cuerpo, err := json.Marshal(map[string]string{"escena": escena, "modelo": modelo})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.cfg.ModeloURL+"/validar", bytes.NewReader(cuerpo))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.clienteModelo.Do(req)
	if err != nil {
		return nil, errModeloCaido
	}
	defer resp.Body.Close()
	var res respuestaValidacion
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return nil, fmt.Errorf("Respuesta inválida del modelo (%s)", resp.Status)
	}
	if resp.StatusCode != http.StatusOK {
		var detalle string
		if json.Unmarshal(res.Detalle, &detalle) != nil || detalle == "" {
			detalle = fmt.Sprintf("El modelo respondió %s", resp.Status)
		}
		return nil, errors.New(detalle)
	}
	return &res, nil
}

func (a *App) marcarErrorValidacion(ctx context.Context, id int64, mensaje string) {
	if _, err := a.db.Exec(ctx, `UPDATE validaciones SET estado = 'error', mensaje = $2, terminado = now() WHERE id = $1`, id, mensaje); err != nil {
		log.Printf("validación %d: %v", id, err)
	}
}

// listarValidaciones: las escenas, los modelos y el estado de cada validación (sin geometrías; el mapa pide la que se ve).
func (a *App) listarValidaciones(w http.ResponseWriter, r *http.Request, s *Sesion) {
	c, err := a.catalogo(r.Context())
	servicio := err == nil
	filas, err := a.db.Query(r.Context(), `
		SELECT id, escena, modelo, estado, mensaje, terminado FROM validaciones ORDER BY escena, modelo`)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	lista, err := pgx.CollectRows(filas, func(f pgx.CollectableRow) (ResumenValidacion, error) {
		var v ResumenValidacion
		err := f.Scan(&v.ID, &v.Escena, &v.Modelo, &v.Estado, &v.Mensaje, &v.Terminado)
		return v, err
	})
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if c.Escenas == nil {
		c.Escenas = []escenaValidacion{}
	}
	if c.Modelos == nil {
		c.Modelos = []modeloCatalogo{}
	}
	responderJSON(w, http.StatusOK, map[string]any{
		"servicio": servicio, "escenas": c.Escenas, "modelos": c.Modelos, "validaciones": lista})
}

// verValidacion: una validación con sus tres capas como FeatureCollection (propiedad capa = aciertos, falsas u omisiones).
func (a *App) verValidacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	id, ok := idDeRuta(r)
	if !ok {
		responderError(w, http.StatusBadRequest, "Validación inválida")
		return
	}
	var v struct {
		ResumenValidacion
		Referencia string            `json:"referencia"`
		BBox       [4]float64        `json:"bbox"`
		Info       *escenaValidacion `json:"info_escena"` // nil si el servicio del modelo no responde
		Capas      json.RawMessage   `json:"capas"`
	}
	var capas []byte
	err := a.db.QueryRow(r.Context(), `
		SELECT v.id, v.escena, v.modelo, v.estado, v.mensaje, v.terminado, v.referencia,
		       ST_XMin(v.area), ST_YMin(v.area), ST_XMax(v.area), ST_YMax(v.area),
		       COALESCE((SELECT json_agg(json_build_object('type', 'Feature', 'properties', json_build_object('capa', c.capa),
		                                                   'geometry', ST_AsGeoJSON(c.geom, 6)::json) ORDER BY c.orden)
		                 FROM (VALUES (1, 'omisiones', v.omisiones), (2, 'falsas', v.falsas), (3, 'aciertos', v.aciertos))
		                      c(orden, capa, geom) WHERE c.geom IS NOT NULL), '[]'::json)
		FROM validaciones v WHERE v.id = $1`, id).
		Scan(&v.ID, &v.Escena, &v.Modelo, &v.Estado, &v.Mensaje, &v.Terminado, &v.Referencia,
			&v.BBox[0], &v.BBox[1], &v.BBox[2], &v.BBox[3], &capas)
	if errors.Is(err, pgx.ErrNoRows) {
		responderError(w, http.StatusNotFound, "La validación no existe")
		return
	}
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	v.Capas = json.RawMessage(fmt.Sprintf(`{"type":"FeatureCollection","features":%s}`, capas))
	if c, err := a.catalogo(r.Context()); err == nil {
		for i := range c.Escenas {
			if c.Escenas[i].Clave == v.Escena {
				v.Info = &c.Escenas[i]
			}
		}
	}
	responderJSON(w, http.StatusOK, v)
}

// recalcularValidacion vuelve a poner en cola una validación terminada (por ejemplo, después de cambiar un modelo).
// Solo si están los recortes NISAR de la zona: en un servidor que recibió las validaciones ya calculadas (con la base de
// datos) se borrarían los polígonos y luego fallaría.
func (a *App) recalcularValidacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	id, ok := idDeRuta(r)
	if !ok {
		responderError(w, http.StatusBadRequest, "Validación inválida")
		return
	}
	var escena string
	if err := a.db.QueryRow(r.Context(), `SELECT escena FROM validaciones WHERE id = $1`, id).Scan(&escena); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			responderError(w, http.StatusNotFound, "La validación no existe")
		} else {
			a.errorInterno(w, err)
		}
		return
	}
	c, err := a.catalogo(r.Context())
	if err != nil {
		responderError(w, http.StatusServiceUnavailable, "El servicio del modelo no responde")
		return
	}
	disponible := false
	for _, e := range c.Escenas {
		if e.Clave == escena {
			disponible = e.Disponible
		}
	}
	if !disponible {
		responderError(w, http.StatusConflict, "Aquí no están los recortes NISAR de esa zona: la validación se queda como está")
		return
	}
	etiqueta, err := a.db.Exec(r.Context(), `UPDATE validaciones SET estado = 'pendiente', mensaje = '', intentos = 0,
		referencia = '', aciertos = NULL, falsas = NULL, omisiones = NULL, segundos = NULL, iniciado = NULL, terminado = NULL
		WHERE id = $1 AND estado IN ('completado', 'error')`, id)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if etiqueta.RowsAffected() == 0 {
		responderError(w, http.StatusConflict, "Solo se puede recalcular una validación terminada")
		return
	}
	a.avisarCola()
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}
