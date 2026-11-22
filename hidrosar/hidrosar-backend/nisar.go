package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"net/http"
	"net/url"
	"slices"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	urlASF       = "https://api.daac.asf.alaska.edu/services/search/param"
	urlOpenMeteo = "https://historical-forecast-api.open-meteo.com/v1/forecast"
	formatoHora  = "2006-01-02 15:04"
)

// Pasada: una toma de NISAR sobre el área; puede venir en uno o más cuadros (frames) seguidos de la misma órbita.
type Pasada struct {
	InicioUTC    time.Time `json:"inicio_utc"`
	HoraLocal    string    `json:"hora_local"`
	Pista        int       `json:"pista"`
	Direccion    string    `json:"direccion"`
	Cuadros      []int     `json:"cuadros"`
	Archivos     []string  `json:"archivos"`
	URLs         []string  `json:"urls"`
	CoberturaPct *float64  `json:"cobertura_pct"`
	Lluvia24hMM  *float64  `json:"lluvia_24h_mm"`
	Lluvia72hMM  *float64  `json:"lluvia_72h_mm"`
	huellas      [][][2]float64
}

type PasadaLluvia struct {
	Pasada
	Referencias []Pasada `json:"referencias"`
	Aviso       string   `json:"aviso,omitempty"`
}

type ResultadoBusqueda struct {
	ID          string         `json:"busqueda_id"`
	BBox        [4]float64     `json:"bbox"`
	Fecha       string         `json:"fecha"`
	ZonaHoraria string         `json:"zona_horaria"`
	Encontrada  bool           `json:"encontrada"`
	Mensaje     string         `json:"mensaje"`
	Pasadas     []PasadaLluvia `json:"pasadas"`
	Anterior    *Pasada        `json:"anterior,omitempty"`
	Siguiente   *Pasada        `json:"siguiente,omitempty"`
}

type granulo struct {
	archivo, url, direccion string
	inicio, procesado       time.Time
	pista, cuadro           int
	huella                  [][2]float64
}

func (a *App) validarArea(b [4]float64) error {
	o, s, e, n := b[0], b[1], b[2], b[3]
	if o < -180 || e > 180 || s < -90 || n > 90 || o >= e || s >= n {
		return errors.New("El área no es válida")
	}
	ancho := (e - o) * 111.32 * math.Cos((s+n)/2*math.Pi/180)
	alto := (n - s) * 110.57
	if ancho < 1 || alto < 1 {
		return errors.New("El área debe medir al menos 1 km por lado")
	}
	if ancho*alto > a.cfg.MaxAreaKm2 {
		return fmt.Errorf("El área (%.0f km²) supera el máximo de %.0f km²", ancho*alto, a.cfg.MaxAreaKm2)
	}
	return nil
}

func (a *App) consultarASF(ctx context.Context, b [4]float64, desde, hasta time.Time) ([]granulo, error) {
	o, s, e, n := b[0], b[1], b[2], b[3]
	q := url.Values{
		"platform":        {"NISAR"},
		"processingLevel": {"RSLC"},
		"output":          {"geojson"},
		"intersectsWith":  {fmt.Sprintf("POLYGON((%.5f %.5f,%.5f %.5f,%.5f %.5f,%.5f %.5f,%.5f %.5f))", o, s, e, s, e, n, o, n, o, s)},
		"start":           {desde.UTC().Format(time.RFC3339)},
		"end":             {hasta.UTC().Format(time.RFC3339)},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, urlASF+"?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	resp, err := a.cliente.Do(req)
	if err != nil {
		return nil, fmt.Errorf("no se pudo consultar el archivo de NISAR en ASF: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("el archivo de NISAR en ASF respondió %s", resp.Status)
	}
	var datos struct {
		Features []struct {
			Properties struct {
				FileID               string   `json:"fileID"`
				URL                  string   `json:"url"`
				StartTime            string   `json:"startTime"`
				ProcessingDate       string   `json:"processingDate"`
				PathNumber           int      `json:"pathNumber"`
				FrameNumber          int      `json:"frameNumber"`
				FlightDirection      string   `json:"flightDirection"`
				MainBandPolarization []string `json:"mainBandPolarization"`
			} `json:"properties"`
			Geometry struct {
				Type        string          `json:"type"`
				Coordinates json.RawMessage `json:"coordinates"`
			} `json:"geometry"`
		} `json:"features"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&datos); err != nil {
		return nil, fmt.Errorf("respuesta inesperada de ASF: %w", err)
	}
	unicos := map[string]granulo{}
	for _, f := range datos.Features {
		p := f.Properties
		if !strings.HasSuffix(p.URL, ".h5") {
			continue
		}
		if len(p.MainBandPolarization) > 0 && !slices.Contains(p.MainBandPolarization, "HH") {
			continue
		}
		inicio, err := time.Parse(time.RFC3339, p.StartTime)
		if err != nil {
			continue
		}
		procesado, _ := time.Parse(time.RFC3339, p.ProcessingDate)
		g := granulo{archivo: p.FileID, url: p.URL, direccion: direccionES(p.FlightDirection), inicio: inicio,
			procesado: procesado, pista: p.PathNumber, cuadro: p.FrameNumber}
		if f.Geometry.Type == "Polygon" {
			var anillos [][][2]float64
			if json.Unmarshal(f.Geometry.Coordinates, &anillos) == nil && len(anillos) > 0 {
				g.huella = anillos[0]
			}
		}
		clave := fmt.Sprintf("%d/%d/%s", g.pista, g.cuadro, inicio.Format(time.RFC3339))
		if previo, existe := unicos[clave]; !existe || procesado.After(previo.procesado) {
			unicos[clave] = g
		}
	}
	granulos := make([]granulo, 0, len(unicos))
	for _, g := range unicos {
		granulos = append(granulos, g)
	}
	sort.Slice(granulos, func(i, j int) bool { return granulos[i].inicio.Before(granulos[j].inicio) })
	return granulos, nil
}

func direccionES(d string) string {
	switch strings.ToUpper(d) {
	case "ASCENDING":
		return "ascendente"
	case "DESCENDING":
		return "descendente"
	}
	return strings.ToLower(d)
}

func agrupar(granulos []granulo, zona *time.Location, b [4]float64) []Pasada {
	var pasadas []Pasada
	for _, g := range granulos {
		k := slices.IndexFunc(pasadas, func(p Pasada) bool {
			return p.Pista == g.pista && p.Direccion == g.direccion && g.inicio.Sub(p.InicioUTC).Abs() < 10*time.Minute
		})
		if k < 0 {
			pasadas = append(pasadas, Pasada{InicioUTC: g.inicio, Pista: g.pista, Direccion: g.direccion})
			k = len(pasadas) - 1
		}
		p := &pasadas[k]
		if g.inicio.Before(p.InicioUTC) {
			p.InicioUTC = g.inicio
		}
		p.Cuadros = append(p.Cuadros, g.cuadro)
		p.Archivos = append(p.Archivos, g.archivo)
		p.URLs = append(p.URLs, g.url)
		if g.huella != nil {
			p.huellas = append(p.huellas, g.huella)
		}
	}
	for i := range pasadas {
		p := &pasadas[i]
		p.HoraLocal = p.InicioUTC.In(zona).Format(formatoHora)
		p.CoberturaPct = cobertura(b, p.huellas)
	}
	return pasadas
}

func cobertura(b [4]float64, huellas [][][2]float64) *float64 {
	if len(huellas) == 0 {
		return nil
	}
	dentro, total := 0, 0
	for i := 0; i <= 10; i++ {
		for j := 0; j <= 10; j++ {
			x := b[0] + (b[2]-b[0])*float64(i)/10
			y := b[1] + (b[3]-b[1])*float64(j)/10
			total++
			for _, h := range huellas {
				if puntoEnPoligono(x, y, h) {
					dentro++
					break
				}
			}
		}
	}
	pct := math.Round(1000*float64(dentro)/float64(total)) / 10
	return &pct
}

func puntoEnPoligono(x, y float64, anillo [][2]float64) bool {
	dentro := false
	for i, j := 0, len(anillo)-1; i < len(anillo); j, i = i, i+1 {
		xi, yi, xj, yj := anillo[i][0], anillo[i][1], anillo[j][0], anillo[j][1]
		if (yi > y) != (yj > y) && x < (xj-xi)*(y-yi)/(yj-yi)+xi {
			dentro = !dentro
		}
	}
	return dentro
}

// lluviaHoraria: precipitación horaria (mm) del modelo meteorológico de Open-Meteo en un punto, indexada por hora UTC.
func (a *App) lluviaHoraria(ctx context.Context, lat, lon float64, desde, hasta time.Time) (map[int64]float64, error) {
	if hoy := time.Now().UTC(); hasta.After(hoy) {
		hasta = hoy
	}
	q := url.Values{
		"latitude": {fmt.Sprintf("%.4f", lat)}, "longitude": {fmt.Sprintf("%.4f", lon)},
		"start_date": {desde.UTC().Format("2006-01-02")}, "end_date": {hasta.UTC().Format("2006-01-02")},
		"hourly": {"precipitation"}, "timezone": {"GMT"},
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, urlOpenMeteo+"?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	resp, err := a.cliente.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Open-Meteo respondió %s", resp.Status)
	}
	var datos struct {
		Hourly struct {
			Time          []string   `json:"time"`
			Precipitation []*float64 `json:"precipitation"`
		} `json:"hourly"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&datos); err != nil {
		return nil, err
	}
	lluvia := make(map[int64]float64, len(datos.Hourly.Time))
	for i, t := range datos.Hourly.Time {
		hora, err := time.Parse("2006-01-02T15:04", t)
		if err == nil && i < len(datos.Hourly.Precipitation) && datos.Hourly.Precipitation[i] != nil {
			lluvia[hora.Unix()] = *datos.Hourly.Precipitation[i]
		}
	}
	return lluvia, nil
}

func sumaLluvia(lluvia map[int64]float64, hasta time.Time, horas int) *float64 {
	if lluvia == nil {
		return nil
	}
	fin := hasta.UTC().Truncate(time.Hour)
	total, n := 0.0, 0
	for h := 0; h < horas; h++ {
		if v, ok := lluvia[fin.Add(-time.Duration(h)*time.Hour).Unix()]; ok {
			total += v
			n++
		}
	}
	if n == 0 {
		return nil
	}
	total = math.Round(total*10) / 10
	return &total
}

// elegirReferencias: hasta 2 pasadas secas de la misma pista (misma geometría de toma), primero las anteriores a la lluvia.
func elegirReferencias(p Pasada, todas []Pasada) PasadaLluvia {
	var antes, despues []Pasada
	for _, q := range todas {
		if q.Pista != p.Pista || q.Direccion != p.Direccion {
			continue
		}
		switch d := q.InicioUTC.Sub(p.InicioUTC); {
		case d <= -24*time.Hour:
			antes = append(antes, q)
		case d >= 72*time.Hour:
			despues = append(despues, q)
		}
	}
	sort.Slice(antes, func(i, j int) bool { return antes[i].InicioUTC.After(antes[j].InicioUTC) })
	candidatas := append(antes, despues...)
	seca := func(q Pasada) bool { return q.Lluvia72hMM != nil && *q.Lluvia72hMM < 1 }
	var refs []Pasada
	for _, q := range candidatas {
		if len(refs) < 2 && seca(q) {
			refs = append(refs, q)
		}
	}
	aviso := ""
	if len(refs) < 2 {
		for _, q := range candidatas {
			if len(refs) < 2 && !seca(q) {
				refs = append(refs, q)
				aviso = "Alguna referencia tuvo lluvia en las 72 h previas o no se pudo verificar: el resultado puede marcar menos agua de lluvia."
			}
		}
	}
	if len(refs) == 0 {
		aviso = "No hay otra pasada de la misma pista para comparar: se usará solo el agua permanente como referencia (resultado menos confiable)."
	}
	if refs == nil {
		refs = []Pasada{}
	}
	return PasadaLluvia{Pasada: p, Referencias: refs, Aviso: aviso}
}

func (a *App) buscarNisar(w http.ResponseWriter, r *http.Request, s *Sesion) {
	var datos struct {
		BBox  [4]float64 `json:"bbox"`
		Fecha string     `json:"fecha"`
	}
	if err := leerJSON(w, r, &datos); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	if err := a.validarArea(datos.BBox); err != nil {
		responderError(w, http.StatusBadRequest, err.Error())
		return
	}
	dia, err := time.ParseInLocation("2006-01-02", datos.Fecha, a.cfg.Zona)
	if err != nil {
		responderError(w, http.StatusBadRequest, "La fecha no es válida")
		return
	}
	if dia.After(time.Now()) {
		responderError(w, http.StatusBadRequest, "La fecha no puede ser futura")
		return
	}
	ctx := r.Context()
	granulos, err := a.consultarASF(ctx, datos.BBox, dia.AddDate(0, 0, -72), dia.AddDate(0, 0, 14))
	if err != nil {
		log.Printf("búsqueda NISAR: %v", err)
		responderError(w, http.StatusBadGateway, "No se pudo consultar el archivo de NISAR (ASF). Intenta de nuevo en unos minutos.")
		return
	}
	pasadas := agrupar(granulos, a.cfg.Zona, datos.BBox)
	lat, lon := (datos.BBox[1]+datos.BBox[3])/2, (datos.BBox[0]+datos.BBox[2])/2
	lluvia, err := a.lluviaHoraria(ctx, lat, lon, dia.AddDate(0, 0, -76), dia.AddDate(0, 0, 15))
	if err != nil {
		log.Printf("lluvia Open-Meteo: %v", err)
		lluvia = nil
	}
	for i := range pasadas {
		pasadas[i].Lluvia24hMM = sumaLluvia(lluvia, pasadas[i].InicioUTC, 24)
		pasadas[i].Lluvia72hMM = sumaLluvia(lluvia, pasadas[i].InicioUTC, 72)
	}

	fin := dia.AddDate(0, 0, 1)
	res := &ResultadoBusqueda{BBox: datos.BBox, Fecha: datos.Fecha, ZonaHoraria: a.cfg.Zona.String(), Pasadas: []PasadaLluvia{}}
	var horas []string
	for _, p := range pasadas {
		switch {
		case p.InicioUTC.Before(dia):
			anterior := p
			res.Anterior = &anterior
		case p.InicioUTC.Before(fin):
			res.Pasadas = append(res.Pasadas, elegirReferencias(p, pasadas))
			horas = append(horas, p.HoraLocal[11:])
		case res.Siguiente == nil:
			siguiente := p
			res.Siguiente = &siguiente
		}
	}
	fechaTexto := dia.Format("02/01/2006")
	if res.Encontrada = len(res.Pasadas) > 0; res.Encontrada {
		res.Mensaje = fmt.Sprintf("Se encontró el radar NISAR el %s a las %s (hora local)", fechaTexto, strings.Join(horas, " y "))
		res.Anterior, res.Siguiente = nil, nil
	} else {
		res.Mensaje = fmt.Sprintf("No se encontró el radar NISAR sobre el área el %s", fechaTexto)
	}
	res.ID = a.busquedas.guardar(res, s.ID)
	responderJSON(w, http.StatusOK, res)
}

type cacheBusquedas struct {
	mu    sync.Mutex
	ttl   time.Duration
	datos map[string]entradaBusqueda
}

type entradaBusqueda struct {
	res     *ResultadoBusqueda
	usuario int64
	creada  time.Time
}

func nuevaCache(ttl time.Duration) *cacheBusquedas {
	return &cacheBusquedas{ttl: ttl, datos: map[string]entradaBusqueda{}}
}

func (c *cacheBusquedas) guardar(res *ResultadoBusqueda, usuario int64) string {
	bytes := make([]byte, 16)
	_, _ = rand.Read(bytes)
	id := hex.EncodeToString(bytes)
	c.mu.Lock()
	defer c.mu.Unlock()
	for k, v := range c.datos {
		if time.Since(v.creada) > c.ttl {
			delete(c.datos, k)
		}
	}
	c.datos[id] = entradaBusqueda{res: res, usuario: usuario, creada: time.Now()}
	return id
}

func (c *cacheBusquedas) obtener(id string, usuario int64) (*ResultadoBusqueda, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.datos[id]
	if !ok || e.usuario != usuario || time.Since(e.creada) > c.ttl {
		return nil, false
	}
	return e.res, true
}
