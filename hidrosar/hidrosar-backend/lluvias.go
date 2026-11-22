package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Lista de lluvias del Perú: lluvia diaria de Open-Meteo (la misma fuente de la búsqueda NISAR) en las capitales de región
// y ciudades principales, con las pasadas de NISAR que cubren cada ciudad el mismo día o el siguiente.

const (
	inicioNisar  = "2025-07-30" // lanzamiento de NISAR
	maxDiasRango = 366
	maxEventos   = 1500
)

type Ciudad struct {
	Nombre string  `json:"nombre"`
	Lat    float64 `json:"lat"`
	Lon    float64 `json:"lon"`
}

type Region struct {
	Nombre   string   `json:"region"`
	Ciudades []Ciudad `json:"ciudades"`
}

// Centro aproximado de cada ciudad (±1 km): basta para la lluvia de un modelo meteorológico y para centrar el mapa.
var regionesPeru = []Region{
	{"Amazonas", []Ciudad{{"Chachapoyas", -6.2296, -77.8722}, {"Bagua Grande", -5.7570, -78.4410}, {"Bagua", -5.6390, -78.5310}}},
	{"Áncash", []Ciudad{{"Huaraz", -9.5279, -77.5278}, {"Chimbote", -9.0745, -78.5936}, {"Casma", -9.4748, -78.3058}}},
	{"Apurímac", []Ciudad{{"Abancay", -13.6339, -72.8814}, {"Andahuaylas", -13.6556, -73.3872}}},
	{"Arequipa", []Ciudad{{"Arequipa", -16.3988, -71.5369}, {"Camaná", -16.6228, -72.7111}, {"Mollendo", -17.0231, -72.0147}}},
	{"Ayacucho", []Ciudad{{"Ayacucho", -13.1600, -74.2240}, {"Huanta", -12.9393, -74.2477}, {"Puquio", -14.6970, -74.1250}}},
	{"Cajamarca", []Ciudad{{"Cajamarca", -7.1569, -78.5175}, {"Jaén", -5.7083, -78.8081}, {"Chota", -6.5611, -78.6497}}},
	{"Callao", []Ciudad{{"Callao", -12.0560, -77.1260}}},
	{"Cusco", []Ciudad{{"Cusco", -13.5163, -71.9786}, {"Quillabamba", -12.8630, -72.6920}, {"Sicuani", -14.2700, -71.2260}}},
	{"Huancavelica", []Ciudad{{"Huancavelica", -12.7870, -74.9760}}},
	{"Huánuco", []Ciudad{{"Huánuco", -9.9295, -76.2397}, {"Tingo María", -9.2950, -75.9970}}},
	{"Ica", []Ciudad{{"Ica", -14.0639, -75.7292}, {"Chincha Alta", -13.4180, -76.1320}, {"Pisco", -13.7100, -76.2050}, {"Nasca", -14.8300, -74.9420}}},
	{"Junín", []Ciudad{{"Huancayo", -12.0681, -75.2100}, {"Tarma", -11.4190, -75.6900}, {"La Merced", -11.0550, -75.3280}, {"Satipo", -11.2520, -74.6380}}},
	{"La Libertad", []Ciudad{{"Trujillo", -8.1118, -79.0287}, {"Chepén", -7.2270, -79.4300}, {"Pacasmayo", -7.4010, -79.5710}, {"Huamachuco", -7.8130, -78.0490}}},
	{"Lambayeque", []Ciudad{{"Chiclayo", -6.7714, -79.8409}, {"Lambayeque", -6.7020, -79.9060}, {"Ferreñafe", -6.6390, -79.7890}}},
	{"Lima", []Ciudad{{"Lima Centro", -12.0464, -77.0428}, {"Lima Norte (Comas)", -11.9400, -77.0550}, {"Lima Este (Ate)", -12.0260, -76.9180},
		{"Lima Sur (VES y VMT)", -12.2000, -76.9400}, {"Huaral", -11.4950, -77.2078}, {"Huacho", -11.1067, -77.6050},
		{"Barranca", -10.7539, -77.7611}, {"Cañete", -13.0775, -76.3869}}},
	{"Loreto", []Ciudad{{"Iquitos", -3.7491, -73.2538}, {"Yurimaguas", -5.9020, -76.1220}, {"Nauta", -4.5083, -73.5833}}},
	{"Madre de Dios", []Ciudad{{"Puerto Maldonado", -12.5933, -69.1891}}},
	{"Moquegua", []Ciudad{{"Moquegua", -17.1940, -70.9350}, {"Ilo", -17.6390, -71.3380}}},
	{"Pasco", []Ciudad{{"Cerro de Pasco", -10.6860, -76.2630}, {"Oxapampa", -10.5770, -75.4050}}},
	{"Piura", []Ciudad{{"Piura", -5.1945, -80.6328}, {"Sullana", -4.9039, -80.6853}, {"Paita", -5.0892, -81.1144}, {"Talara", -4.5772, -81.2719},
		{"Chulucanas", -5.0925, -80.1625}}},
	{"Puno", []Ciudad{{"Puno", -15.8402, -70.0219}, {"Juliaca", -15.4970, -70.1330}}},
	{"San Martín", []Ciudad{{"Moyobamba", -6.0342, -76.9717}, {"Tarapoto", -6.4825, -76.3656}, {"Juanjuí", -7.1772, -76.7278}}},
	{"Tacna", []Ciudad{{"Tacna", -18.0130, -70.2500}}},
	{"Tumbes", []Ciudad{{"Tumbes", -3.5669, -80.4515}, {"Zarumilla", -3.5014, -80.2747}, {"Zorritos", -3.6800, -80.6780}}},
	{"Ucayali", []Ciudad{{"Pucallpa", -8.3791, -74.5539}, {"Atalaya", -10.7297, -73.7553}}},
}

type diaLluvia struct {
	fecha string
	mm    float64
	horas *float64
}

type PasadaCercana struct {
	HoraLocal string `json:"hora_local"`
	Pista     int    `json:"pista"`
	Direccion string `json:"direccion"`
	Dia       string `json:"dia"` // "mismo" o "siguiente"
}

type EventoLluvia struct {
	Fecha  string          `json:"fecha"`
	Region string          `json:"region"`
	Ciudad string          `json:"ciudad"`
	Lat    float64         `json:"lat"`
	Lon    float64         `json:"lon"`
	MM     float64         `json:"mm"`
	Horas  *float64        `json:"horas"`
	Nisar  []PasadaCercana `json:"nisar"`
}

type RespuestaLluvias struct {
	Region          string         `json:"region"`
	Ciudad          string         `json:"ciudad"`
	Desde           string         `json:"desde"`
	Hasta           string         `json:"hasta"`
	MinimoMM        float64        `json:"minimo_mm"`
	Total           int            `json:"total"`
	NisarConsultado bool           `json:"nisar_consultado"`
	Aviso           string         `json:"aviso,omitempty"`
	Eventos         []EventoLluvia `json:"eventos"`
}

// cacheTTL guarda respuestas de servicios externos por un tiempo, para no repetir consultas iguales.
type cacheTTL[T any] struct {
	mu    sync.Mutex
	ttl   time.Duration
	datos map[string]entradaTTL[T]
}

type entradaTTL[T any] struct {
	valor  T
	creada time.Time
}

func nuevaCacheTTL[T any](ttl time.Duration) *cacheTTL[T] {
	return &cacheTTL[T]{ttl: ttl, datos: map[string]entradaTTL[T]{}}
}

func (c *cacheTTL[T]) obtener(clave string) (T, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.datos[clave]
	if !ok || time.Since(e.creada) > c.ttl {
		var cero T
		return cero, false
	}
	return e.valor, true
}

func (c *cacheTTL[T]) guardar(clave string, valor T) {
	c.mu.Lock()
	defer c.mu.Unlock()
	for k, v := range c.datos {
		if time.Since(v.creada) > c.ttl {
			delete(c.datos, k)
		}
	}
	c.datos[clave] = entradaTTL[T]{valor: valor, creada: time.Now()}
}

func (a *App) listarRegiones(w http.ResponseWriter, r *http.Request, s *Sesion) {
	responderJSON(w, http.StatusOK, regionesPeru)
}

func (a *App) listarLluvias(w http.ResponseWriter, r *http.Request, s *Sesion) {
	q := r.URL.Query()
	zona := a.cfg.Zona
	hoy := time.Now().In(zona).Format("2006-01-02")
	desde, hasta := q.Get("desde"), q.Get("hasta")
	if hasta > hoy {
		hasta = hoy
	}
	d0, err0 := time.ParseInLocation("2006-01-02", desde, zona)
	d1, err1 := time.ParseInLocation("2006-01-02", hasta, zona)
	switch {
	case err0 != nil || err1 != nil:
		responderError(w, http.StatusBadRequest, "Las fechas no son válidas")
		return
	case desde < inicioNisar:
		responderError(w, http.StatusBadRequest, "NISAR tiene imágenes desde el 30/07/2025: elige una fecha inicial posterior")
		return
	case d0.After(d1):
		responderError(w, http.StatusBadRequest, "La fecha inicial debe ser anterior a la final")
		return
	case d1.Sub(d0) > maxDiasRango*24*time.Hour:
		responderError(w, http.StatusBadRequest, "El rango máximo es de un año")
		return
	}
	minimo := 1.0
	if texto := q.Get("minimo"); texto != "" {
		v, err := strconv.ParseFloat(strings.ReplaceAll(texto, ",", "."), 64)
		if err != nil || v < 0.1 || v > 500 {
			responderError(w, http.StatusBadRequest, "La lluvia mínima debe estar entre 0.1 y 500 mm")
			return
		}
		minimo = v
	}

	regiones := regionesPeru
	if nombre := q.Get("region"); nombre != "" {
		regiones = nil
		for _, rg := range regionesPeru {
			if rg.Nombre == nombre {
				regiones = []Region{rg}
			}
		}
		if regiones == nil {
			responderError(w, http.StatusBadRequest, "Región desconocida")
			return
		}
		if ciudad := q.Get("ciudad"); ciudad != "" {
			var elegidas []Ciudad
			for _, c := range regiones[0].Ciudades {
				if c.Nombre == ciudad {
					elegidas = append(elegidas, c)
				}
			}
			if elegidas == nil {
				responderError(w, http.StatusBadRequest, "Ciudad desconocida")
				return
			}
			regiones = []Region{{regiones[0].Nombre, elegidas}}
		}
	}

	var ciudades []Ciudad
	var regionDe []string
	for _, rg := range regiones {
		for _, c := range rg.Ciudades {
			ciudades = append(ciudades, c)
			regionDe = append(regionDe, rg.Nombre)
		}
	}
	ctx := r.Context()
	dias, err := a.lluviaDiaria(ctx, ciudades, desde, hasta)
	if err != nil {
		log.Printf("lluvias Open-Meteo: %v", err)
		responderError(w, http.StatusBadGateway, "No se pudo consultar la lluvia en Open-Meteo. Intenta de nuevo en unos minutos.")
		return
	}
	pasadas, fallas := a.pasadasPorCiudad(ctx, regiones, d0, d1.AddDate(0, 0, 2))

	res := RespuestaLluvias{Region: q.Get("region"), Ciudad: q.Get("ciudad"), Desde: desde, Hasta: hasta, MinimoMM: minimo,
		NisarConsultado: fallas < len(regiones), Eventos: []EventoLluvia{}}
	if fallas > 0 {
		res.Aviso = "No se pudo consultar NISAR (ASF) para todas las regiones: algunas pasadas pueden faltar."
	}
	for i, c := range ciudades {
		porDia := map[string][]Pasada{}
		for _, p := range pasadas[regionDe[i]+"/"+c.Nombre] {
			dia := p.InicioUTC.In(zona).Format("2006-01-02")
			porDia[dia] = append(porDia[dia], p)
		}
		for _, d := range dias[i] {
			if d.mm < minimo {
				continue
			}
			ev := EventoLluvia{Fecha: d.fecha, Region: regionDe[i], Ciudad: c.Nombre, Lat: c.Lat, Lon: c.Lon, MM: d.mm, Horas: d.horas,
				Nisar: []PasadaCercana{}}
			dia, _ := time.ParseInLocation("2006-01-02", d.fecha, zona)
			for _, cual := range []struct{ fecha, nombre string }{{d.fecha, "mismo"}, {dia.AddDate(0, 0, 1).Format("2006-01-02"), "siguiente"}} {
				for _, p := range porDia[cual.fecha] {
					ev.Nisar = append(ev.Nisar, PasadaCercana{HoraLocal: p.HoraLocal, Pista: p.Pista, Direccion: p.Direccion, Dia: cual.nombre})
				}
			}
			res.Eventos = append(res.Eventos, ev)
		}
	}
	sort.SliceStable(res.Eventos, func(i, j int) bool {
		if res.Eventos[i].Fecha != res.Eventos[j].Fecha {
			return res.Eventos[i].Fecha > res.Eventos[j].Fecha
		}
		return res.Eventos[i].MM > res.Eventos[j].MM
	})
	res.Total = len(res.Eventos)
	if res.Total > maxEventos {
		res.Eventos = res.Eventos[:maxEventos]
		res.Aviso = strings.TrimSpace(res.Aviso + fmt.Sprintf(" Se muestran los %d días más recientes de %d: sube la lluvia mínima o elige una región.", maxEventos, res.Total))
	}
	responderJSON(w, http.StatusOK, res)
}

// lluviaDiaria pide a Open-Meteo, en una sola consulta, la lluvia diaria (hora local) de las ciudades que no están en caché.
func (a *App) lluviaDiaria(ctx context.Context, ciudades []Ciudad, desde, hasta string) ([][]diaLluvia, error) {
	clave := func(c Ciudad) string { return fmt.Sprintf("%.4f,%.4f|%s|%s", c.Lat, c.Lon, desde, hasta) }
	res := make([][]diaLluvia, len(ciudades))
	var faltan []int
	for i, c := range ciudades {
		if d, ok := a.cacheLluvia.obtener(clave(c)); ok {
			res[i] = d
		} else {
			faltan = append(faltan, i)
		}
	}
	if len(faltan) == 0 {
		return res, nil
	}
	lats, lons := make([]string, len(faltan)), make([]string, len(faltan))
	for k, i := range faltan {
		lats[k], lons[k] = fmt.Sprintf("%.4f", ciudades[i].Lat), fmt.Sprintf("%.4f", ciudades[i].Lon)
	}
	q := url.Values{
		"latitude": {strings.Join(lats, ",")}, "longitude": {strings.Join(lons, ",")},
		"daily": {"precipitation_sum,precipitation_hours"}, "timezone": {a.cfg.Zona.String()},
		"start_date": {desde}, "end_date": {hasta},
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
	cuerpo, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Open-Meteo respondió %s: %.200s", resp.Status, cuerpo)
	}
	type diaria struct {
		Daily struct {
			Time   []string   `json:"time"`
			Lluvia []*float64 `json:"precipitation_sum"`
			Horas  []*float64 `json:"precipitation_hours"`
		} `json:"daily"`
	}
	var lista []diaria
	if cuerpo = bytes.TrimSpace(cuerpo); len(cuerpo) > 0 && cuerpo[0] == '[' {
		err = json.Unmarshal(cuerpo, &lista)
	} else {
		var una diaria
		err = json.Unmarshal(cuerpo, &una)
		lista = []diaria{una}
	}
	if err != nil {
		return nil, err
	}
	if len(lista) != len(faltan) {
		return nil, fmt.Errorf("Open-Meteo devolvió %d ubicaciones de %d", len(lista), len(faltan))
	}
	for k, i := range faltan {
		d := lista[k].Daily
		dias := make([]diaLluvia, 0, len(d.Time))
		for j, fecha := range d.Time {
			if j >= len(d.Lluvia) || d.Lluvia[j] == nil {
				continue
			}
			dl := diaLluvia{fecha: fecha, mm: math.Round(*d.Lluvia[j]*10) / 10}
			if j < len(d.Horas) && d.Horas[j] != nil {
				h := *d.Horas[j]
				dl.horas = &h
			}
			dias = append(dias, dl)
		}
		res[i] = dias
		a.cacheLluvia.guardar(clave(ciudades[i]), dias)
	}
	return res, nil
}

// pasadasPorCiudad consulta ASF una vez por región (como mucho 5 a la vez) y se queda, para cada ciudad, con las pasadas
// cuya huella cubre el punto de la ciudad. Devuelve cuántas regiones no se pudieron consultar.
func (a *App) pasadasPorCiudad(ctx context.Context, regiones []Region, desde, hasta time.Time) (map[string][]Pasada, int) {
	res := map[string][]Pasada{}
	fallas := 0
	var mu sync.Mutex
	var wg sync.WaitGroup
	turnos := make(chan struct{}, 5)
	for _, rg := range regiones {
		wg.Add(1)
		go func() {
			defer wg.Done()
			turnos <- struct{}{}
			granulos, err := a.granulosRegion(ctx, rg, desde, hasta)
			<-turnos
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				log.Printf("lluvias ASF %s: %v", rg.Nombre, err)
				fallas++
				return
			}
			for _, c := range rg.Ciudades {
				var cubren []granulo
				for _, g := range granulos {
					if g.huella != nil && puntoEnPoligono(c.Lon, c.Lat, g.huella) {
						cubren = append(cubren, g)
					}
				}
				caja := [4]float64{c.Lon - 0.005, c.Lat - 0.005, c.Lon + 0.005, c.Lat + 0.005}
				res[rg.Nombre+"/"+c.Nombre] = agrupar(cubren, a.cfg.Zona, caja)
			}
		}()
	}
	wg.Wait()
	return res, fallas
}

func (a *App) granulosRegion(ctx context.Context, rg Region, desde, hasta time.Time) ([]granulo, error) {
	o, s, e, n := 180.0, 90.0, -180.0, -90.0
	for _, c := range rg.Ciudades {
		o, s, e, n = min(o, c.Lon), min(s, c.Lat), max(e, c.Lon), max(n, c.Lat)
	}
	caja := [4]float64{o - 0.02, s - 0.02, e + 0.02, n + 0.02}
	clave := fmt.Sprintf("%v|%s|%s", caja, desde.Format(time.RFC3339), hasta.Format(time.RFC3339))
	if g, ok := a.cacheASF.obtener(clave); ok {
		return g, nil
	}
	g, err := a.consultarASF(ctx, caja, desde, hasta)
	if err != nil {
		return nil, err
	}
	a.cacheASF.guardar(clave, g)
	return g, nil
}
