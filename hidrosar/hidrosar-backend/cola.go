package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
)

type pedidoModelo struct {
	ID          int64      `json:"id"`
	BBox        [4]float64 `json:"bbox"`
	Lluvia      []string   `json:"lluvia"`
	Referencias [][]string `json:"referencias"`
	Modelo      string     `json:"modelo"`
}

type respuestaModelo struct {
	Geometria     json.RawMessage `json:"geometria"`
	Charcos       int             `json:"charcos"`
	AreaM2        float64         `json:"area_m2"`
	Agua          json.RawMessage `json:"agua"`    // toda el agua segmentada ese día; null con los modelos de cambio
	AguaM2        *float64        `json:"agua_m2"` // nil con los modelos de cambio
	MBDescargados float64         `json:"mb_descargados"`
	Metodo        string          `json:"metodo"`
	Aviso         string          `json:"aviso"` // p. ej. la pasada cubre solo parte del área; queda en mensaje
	Detalle       json.RawMessage `json:"detail"`
}

func (a *App) avisarCola() {
	select {
	case a.aviso <- struct{}{}:
	default:
	}
}

// procesarCola atiende las evaluaciones de una en una, en orden de llegada. La cola vive en la base de datos:
// si el backend se reinicia, lo que quedó a medias vuelve a la cola. Cuando no hay evaluaciones esperando, avanza con
// las validaciones de los modelos (una a la vez, y antes de cada una vuelve a mirar si llegó una evaluación).
func (a *App) procesarCola(ctx context.Context) {
	if _, err := a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'en_cola', iniciado = NULL, progreso = NULL WHERE estado = 'procesando'`); err != nil {
		log.Printf("cola: %v", err)
	}
	if _, err := a.db.Exec(ctx, `UPDATE validaciones SET estado = 'pendiente', iniciado = NULL WHERE estado = 'procesando'`); err != nil {
		log.Printf("validaciones: %v", err)
	}
	reloj := time.NewTicker(10 * time.Second)
	defer reloj.Stop()
	var modelos []string
	var sincronizado time.Time
	for {
		if time.Since(sincronizado) > 5*time.Minute {
			if ids, err := a.sincronizarValidaciones(ctx); err == nil {
				modelos, sincronizado = ids, time.Now()
			}
		}
		for a.atenderSiguiente(ctx) || a.validarSiguiente(ctx, modelos) {
		}
		select {
		case <-ctx.Done():
			return
		case <-a.aviso:
		case <-reloj.C:
		}
	}
}

func (a *App) atenderSiguiente(ctx context.Context) bool {
	var p pedidoModelo
	var pasada, referencias []byte
	err := a.db.QueryRow(ctx, `
		UPDATE evaluaciones SET estado = 'procesando', iniciado = now(), progreso = NULL
		WHERE id = (SELECT id FROM evaluaciones WHERE estado = 'en_cola' ORDER BY creado LIMIT 1 FOR UPDATE SKIP LOCKED)
		RETURNING id, ST_XMin(area), ST_YMin(area), ST_XMax(area), ST_YMax(area), pasada, referencias, modelo`).
		Scan(&p.ID, &p.BBox[0], &p.BBox[1], &p.BBox[2], &p.BBox[3], &pasada, &referencias, &p.Modelo)
	if errors.Is(err, pgx.ErrNoRows) || ctx.Err() != nil {
		return false
	}
	if err != nil {
		log.Printf("cola: %v", err)
		return false
	}
	var lluvia Pasada
	var refs []Pasada
	if err := json.Unmarshal(pasada, &lluvia); err != nil {
		a.marcarError(ctx, p.ID, "Datos de la pasada dañados")
		return true
	}
	_ = json.Unmarshal(referencias, &refs)
	p.Lluvia = lluvia.URLs
	p.Referencias = [][]string{}
	for _, r := range refs {
		p.Referencias = append(p.Referencias, r.URLs)
	}
	log.Printf("evaluación %d: enviada al modelo %q (%d cuadro(s), %d referencia(s))", p.ID, p.Modelo, len(p.Lluvia), len(p.Referencias))
	// Mientras el modelo procesa, su avance (pasos, MB descargados) se copia a la base para que el panel lo muestre.
	// Al terminar se guarda una última vez, con el paso que falló si hubo error.
	ctxAvance, pararAvance := context.WithCancel(ctx)
	siguiendo := make(chan struct{})
	go func() {
		defer close(siguiendo)
		a.seguirAvance(ctxAvance, p.ID)
	}()
	res, err := a.llamarModelo(ctx, p)
	pararAvance()
	<-siguiendo
	a.guardarAvance(ctx, p.ID)
	if err != nil {
		if ctx.Err() != nil {
			return false
		}
		log.Printf("evaluación %d: %v", p.ID, err)
		a.marcarError(ctx, p.ID, err.Error())
		return true
	}
	// Sin charcos (o sin agua segmentada) la geometría va NULL: ST_GeomFromGeoJSON(NULL) devuelve NULL
	charcos, geometria := res.Charcos, geoJSONONil(res.Geometria)
	if charcos == 0 || geometria == nil {
		charcos, geometria, res.AreaM2 = 0, nil, 0
	}
	agua := geoJSONONil(res.Agua)
	_, err = a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'completado',
		resultado = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($2::text), 4326)), 3)),
		charcos = $3, area_agua_m2 = $4,
		agua = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($5::text), 4326)), 3)),
		agua_total_m2 = $6, mb_descargados = $7, metodo = $8, mensaje = $9, terminado = now() WHERE id = $1`,
		p.ID, geometria, charcos, res.AreaM2, agua, res.AguaM2, res.MBDescargados, res.Metodo, res.Aviso)
	if err != nil {
		log.Printf("evaluación %d: no se pudo guardar el resultado: %v", p.ID, err)
		a.marcarError(ctx, p.ID, "No se pudo guardar el resultado")
		return true
	}
	log.Printf("evaluación %d: completada (%d charcos)", p.ID, res.Charcos)
	return true
}

func (a *App) seguirAvance(ctx context.Context, id int64) {
	reloj := time.NewTicker(2 * time.Second)
	defer reloj.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-reloj.C:
			a.guardarAvance(ctx, id)
		}
	}
}

// guardarAvance copia a la base el avance que informa el modelo (GET /progreso/{id}). Si no responde, se deja el anterior.
func (a *App) guardarAvance(ctx context.Context, id int64) {
	ctx, listo := context.WithTimeout(ctx, 5*time.Second)
	defer listo()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, fmt.Sprintf("%s/progreso/%d", a.cfg.ModeloURL, id), nil)
	if err != nil {
		return
	}
	resp, err := a.cliente.Do(req)
	if err != nil {
		return
	}
	defer resp.Body.Close()
	var avance json.RawMessage
	if resp.StatusCode != http.StatusOK || json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&avance) != nil {
		return
	}
	if _, err := a.db.Exec(ctx, `UPDATE evaluaciones SET progreso = $2 WHERE id = $1`, id, []byte(avance)); err != nil && ctx.Err() == nil {
		log.Printf("evaluación %d: no se pudo guardar el avance: %v", id, err)
	}
}

// geoJSONONil: la geometría como texto, o nil si el modelo no la mandó
func geoJSONONil(g json.RawMessage) *string {
	s := string(g)
	if s == "" || s == "null" {
		return nil
	}
	return &s
}

func (a *App) llamarModelo(ctx context.Context, p pedidoModelo) (*respuestaModelo, error) {
	cuerpo, err := json.Marshal(p)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.cfg.ModeloURL+"/procesar", bytes.NewReader(cuerpo))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.clienteModelo.Do(req)
	if err != nil {
		return nil, errors.New("El servicio del modelo no responde")
	}
	defer resp.Body.Close()
	var res respuestaModelo
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

func (a *App) marcarError(ctx context.Context, id int64, mensaje string) {
	if _, err := a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'error', mensaje = $2, terminado = now() WHERE id = $1`, id, mensaje); err != nil {
		log.Printf("evaluación %d: %v", id, err)
	}
}
