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

type pedidoModelo struct {
	ID          int64      `json:"id"`
	BBox        [4]float64 `json:"bbox"`
	Lluvia      []string   `json:"lluvia"`
	Referencias [][]string `json:"referencias"`
}

type respuestaModelo struct {
	Geometria     json.RawMessage `json:"geometria"`
	Charcos       int             `json:"charcos"`
	AreaM2        float64         `json:"area_m2"`
	MBDescargados float64         `json:"mb_descargados"`
	Metodo        string          `json:"metodo"`
	Detalle       json.RawMessage `json:"detail"`
}

func (a *App) avisarCola() {
	select {
	case a.aviso <- struct{}{}:
	default:
	}
}

// procesarCola atiende las evaluaciones de una en una, en orden de llegada. La cola vive en la base de datos:
// si el backend se reinicia, lo que quedó a medias vuelve a la cola.
func (a *App) procesarCola(ctx context.Context) {
	if _, err := a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'en_cola', iniciado = NULL WHERE estado = 'procesando'`); err != nil {
		log.Printf("cola: %v", err)
	}
	reloj := time.NewTicker(10 * time.Second)
	defer reloj.Stop()
	for {
		for a.atenderSiguiente(ctx) {
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
		UPDATE evaluaciones SET estado = 'procesando', iniciado = now()
		WHERE id = (SELECT id FROM evaluaciones WHERE estado = 'en_cola' ORDER BY creado LIMIT 1 FOR UPDATE SKIP LOCKED)
		RETURNING id, ST_XMin(area), ST_YMin(area), ST_XMax(area), ST_YMax(area), pasada, referencias`).
		Scan(&p.ID, &p.BBox[0], &p.BBox[1], &p.BBox[2], &p.BBox[3], &pasada, &referencias)
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
	log.Printf("evaluación %d: enviada al modelo (%d cuadro(s), %d referencia(s))", p.ID, len(p.Lluvia), len(p.Referencias))
	res, err := a.llamarModelo(ctx, p)
	if err != nil {
		if ctx.Err() != nil {
			return false
		}
		log.Printf("evaluación %d: %v", p.ID, err)
		a.marcarError(ctx, p.ID, err.Error())
		return true
	}
	geometria := string(res.Geometria)
	if res.Charcos == 0 || geometria == "" || geometria == "null" {
		_, err = a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'completado', resultado = NULL, charcos = 0, area_agua_m2 = 0,
			mb_descargados = $2, metodo = $3, mensaje = '', terminado = now() WHERE id = $1`, p.ID, res.MBDescargados, res.Metodo)
	} else {
		_, err = a.db.Exec(ctx, `UPDATE evaluaciones SET estado = 'completado',
			resultado = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON($2), 4326)), 3)),
			charcos = $3, area_agua_m2 = $4, mb_descargados = $5, metodo = $6, mensaje = '', terminado = now() WHERE id = $1`,
			p.ID, geometria, res.Charcos, res.AreaM2, res.MBDescargados, res.Metodo)
	}
	if err != nil {
		log.Printf("evaluación %d: no se pudo guardar el resultado: %v", p.ID, err)
		a.marcarError(ctx, p.ID, "No se pudo guardar el resultado")
		return true
	}
	log.Printf("evaluación %d: completada (%d charcos)", p.ID, res.Charcos)
	return true
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
