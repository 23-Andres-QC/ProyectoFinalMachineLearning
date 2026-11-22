package main

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Lluvia del Senamhi: tablas horarias de sus estaciones automáticas, tal como se exportan del portal
// (encabezado con la estación y luego una fila por hora con "S/D" cuando no hay dato).

const (
	inicioSenamhi     = "2024-01-01"
	maxArchivoSenamhi = 2 << 20
	maxSubidaSenamhi  = 60 << 20
)

type EstacionSenamhi struct {
	Codigo       string   `json:"codigo"`
	Nombre       string   `json:"nombre"`
	Departamento string   `json:"departamento"`
	Provincia    string   `json:"provincia"`
	Distrito     string   `json:"distrito"`
	Lat          float64  `json:"lat"`
	Lon          float64  `json:"lon"`
	AltitudM     *float64 `json:"altitud_m"`
	Tipo         string   `json:"tipo"`
}

type tablaSenamhi struct {
	estacion EstacionSenamhi
	horas    []string
	mm       []string
}

var numeros = regexp.MustCompile(`\d+(?:\.\d+)?`)

// gradosSur convierte 12°12'41.1'' en grados decimales negativos: todo el Perú está al sur del ecuador y al oeste de Greenwich.
func gradosSur(texto string) (float64, error) {
	p := numeros.FindAllString(texto, 3)
	if len(p) == 0 {
		return 0, fmt.Errorf("coordenada no válida: %q", texto)
	}
	v := 0.0
	for i, s := range p {
		x, _ := strconv.ParseFloat(s, 64)
		v += x / math.Pow(60, float64(i))
	}
	return -v, nil
}

func leerTablaSenamhi(r io.Reader) (*tablaSenamhi, error) {
	datos, err := io.ReadAll(io.LimitReader(r, maxArchivoSenamhi+1))
	if err != nil {
		return nil, err
	}
	if len(datos) > maxArchivoSenamhi {
		return nil, errors.New("el archivo supera 2 MB")
	}
	lector := csv.NewReader(bytes.NewReader(bytes.TrimPrefix(datos, []byte("\xef\xbb\xbf"))))
	lector.FieldsPerRecord = -1
	lector.LazyQuotes = true
	t := &tablaSenamhi{}
	e := &t.estacion
	columna, vistas := -1, map[string]bool{}
	for {
		fila, err := lector.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if len(fila) == 0 {
			continue
		}
		campo := func(i int) string {
			if i < len(fila) {
				return strings.TrimSpace(fila[i])
			}
			return ""
		}
		primero := campo(0)
		switch {
		case strings.HasPrefix(primero, "Estación"):
			if _, nombre, ok := strings.Cut(primero, ":"); ok {
				e.Nombre = strings.TrimSpace(nombre)
			}
		case strings.HasPrefix(primero, "Departamento"):
			e.Departamento, e.Provincia, e.Distrito = campo(1), campo(3), campo(5)
		case strings.HasPrefix(primero, "Latitud"):
			if e.Lat, err = gradosSur(campo(1)); err != nil {
				return nil, err
			}
			if e.Lon, err = gradosSur(campo(3)); err != nil {
				return nil, err
			}
			if a := numeros.FindString(campo(5)); a != "" {
				v, _ := strconv.ParseFloat(a, 64)
				e.AltitudM = &v
			}
		case strings.HasPrefix(primero, "Tipo"):
			e.Tipo, e.Codigo = campo(1), campo(3)
		case strings.HasPrefix(primero, "AÑO"):
			for i, nombre := range fila {
				if strings.HasPrefix(strings.ToUpper(strings.TrimSpace(nombre)), "PRECIPITACI") {
					columna = i
				}
			}
		case columna >= 0:
			dia, err := time.Parse("2006/01/02 15:04", primero+" "+campo(1))
			if err != nil {
				continue
			}
			hora := dia.Format("2006-01-02 15:04")
			if vistas[hora] {
				continue
			}
			vistas[hora] = true
			mm := strings.ReplaceAll(campo(columna), ",", ".")
			if v, err := strconv.ParseFloat(mm, 64); err != nil || v < 0 || v > 300 {
				mm = ""
			}
			t.horas = append(t.horas, hora)
			t.mm = append(t.mm, mm)
		}
	}
	if e.Codigo == "" || e.Nombre == "" || e.Lat == 0 || columna < 0 {
		return nil, errors.New("no es una tabla horaria del Senamhi (faltan la estación, su código, sus coordenadas o la columna de precipitación)")
	}
	if len(t.horas) == 0 {
		return nil, errors.New("la tabla no trae horas")
	}
	return t, nil
}

func guardarTablaSenamhi(ctx context.Context, db *pgxpool.Pool, t *tablaSenamhi) error {
	tx, err := db.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	e := t.estacion
	if _, err := tx.Exec(ctx, `INSERT INTO estaciones_senamhi (codigo, nombre, departamento, provincia, distrito, lat, lon, altitud_m, tipo)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre, departamento = EXCLUDED.departamento,
			provincia = EXCLUDED.provincia, distrito = EXCLUDED.distrito, lat = EXCLUDED.lat, lon = EXCLUDED.lon,
			altitud_m = EXCLUDED.altitud_m, tipo = EXCLUDED.tipo`,
		e.Codigo, e.Nombre, e.Departamento, e.Provincia, e.Distrito, e.Lat, e.Lon, e.AltitudM, e.Tipo); err != nil {
		return err
	}
	// Si dos tablas traen la misma hora, un dato real nunca se reemplaza por "S/D"
	if _, err := tx.Exec(ctx, `INSERT INTO lluvia_senamhi (estacion, hora, mm)
		SELECT $1, h::timestamp, NULLIF(m, '')::real FROM unnest($2::text[], $3::text[]) AS t (h, m)
		ON CONFLICT (estacion, hora) DO UPDATE SET mm = COALESCE(EXCLUDED.mm, lluvia_senamhi.mm)`,
		e.Codigo, t.horas, t.mm); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

type ResultadoArchivo struct {
	Archivo  string `json:"archivo"`
	Estacion string `json:"estacion,omitempty"`
	Horas    int    `json:"horas"`
	Error    string `json:"error,omitempty"`
}

func importarSenamhi(ctx context.Context, db *pgxpool.Pool, nombre string, r io.Reader) ResultadoArchivo {
	res := ResultadoArchivo{Archivo: nombre}
	t, err := leerTablaSenamhi(r)
	if err == nil {
		err = guardarTablaSenamhi(ctx, db, t)
	}
	if err != nil {
		res.Error = err.Error()
		return res
	}
	res.Estacion, res.Horas = t.estacion.Nombre, len(t.horas)
	return res
}

// importarCarpetaSenamhi es el modo de línea de comandos: hidrosar-backend importar-senamhi <carpeta o archivos .csv>
func importarCarpetaSenamhi(ctx context.Context, db *pgxpool.Pool, rutas []string) error {
	var archivos []string
	for _, ruta := range rutas {
		if info, err := os.Stat(ruta); err == nil && info.IsDir() {
			encontrados, _ := filepath.Glob(filepath.Join(ruta, "*.csv"))
			archivos = append(archivos, encontrados...)
		} else {
			archivos = append(archivos, ruta)
		}
	}
	sort.Strings(archivos)
	fallas := 0
	for _, ruta := range archivos {
		f, err := os.Open(ruta)
		if err != nil {
			return err
		}
		res := importarSenamhi(ctx, db, filepath.Base(ruta), f)
		f.Close()
		if res.Error != "" {
			fallas++
			log.Printf("senamhi %s: %s", res.Archivo, res.Error)
		}
	}
	var estaciones, horas, conDato int
	if err := db.QueryRow(ctx, `SELECT (SELECT count(*) FROM estaciones_senamhi), count(*), count(mm) FROM lluvia_senamhi`).
		Scan(&estaciones, &horas, &conDato); err != nil {
		return err
	}
	log.Printf("senamhi: %d archivos leídos (%d con error) · en la base: %d estaciones, %d horas, %d con dato de lluvia",
		len(archivos), fallas, estaciones, horas, conDato)
	if fallas == len(archivos) {
		return errors.New("no se pudo importar ningún archivo")
	}
	return nil
}

func (a *App) subirSenamhi(w http.ResponseWriter, r *http.Request, s *Sesion) {
	r.Body = http.MaxBytesReader(w, r.Body, maxSubidaSenamhi)
	if err := r.ParseMultipartForm(8 << 20); err != nil {
		responderError(w, http.StatusBadRequest, "No se pudieron leer los archivos (máximo 60 MB en total)")
		return
	}
	defer r.MultipartForm.RemoveAll()
	archivos := r.MultipartForm.File["archivos"]
	if len(archivos) == 0 {
		responderError(w, http.StatusBadRequest, "Elige al menos una tabla .csv del Senamhi")
		return
	}
	resultados := []ResultadoArchivo{}
	for _, cabecera := range archivos {
		f, err := cabecera.Open()
		if err != nil {
			resultados = append(resultados, ResultadoArchivo{Archivo: cabecera.Filename, Error: "no se pudo abrir"})
			continue
		}
		resultados = append(resultados, importarSenamhi(r.Context(), a.db, cabecera.Filename, f))
		f.Close()
	}
	log.Printf("senamhi: %s subió %d tablas", s.Email, len(resultados))
	responderJSON(w, http.StatusOK, map[string]any{"archivos": resultados})
}

type ResumenEstacion struct {
	EstacionSenamhi
	Desde        *string `json:"desde"`
	Hasta        *string `json:"hasta"`
	Horas        int     `json:"horas"`
	HorasConDato int     `json:"horas_con_dato"`
}

func (a *App) listarEstacionesSenamhi(w http.ResponseWriter, r *http.Request, s *Sesion) {
	filas, err := a.db.Query(r.Context(), `SELECT e.codigo, e.nombre, e.departamento, e.provincia, e.distrito, e.lat, e.lon, e.altitud_m, e.tipo,
			to_char(min(l.hora) FILTER (WHERE l.mm IS NOT NULL), 'YYYY-MM-DD'),
			to_char(max(l.hora) FILTER (WHERE l.mm IS NOT NULL), 'YYYY-MM-DD'),
			count(l.hora), count(l.mm)
		FROM estaciones_senamhi e LEFT JOIN lluvia_senamhi l ON l.estacion = e.codigo
		GROUP BY e.codigo ORDER BY e.nombre`)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	defer filas.Close()
	lista := []ResumenEstacion{}
	for filas.Next() {
		var e ResumenEstacion
		if err := filas.Scan(&e.Codigo, &e.Nombre, &e.Departamento, &e.Provincia, &e.Distrito, &e.Lat, &e.Lon, &e.AltitudM, &e.Tipo,
			&e.Desde, &e.Hasta, &e.Horas, &e.HorasConDato); err != nil {
			a.errorInterno(w, err)
			return
		}
		lista = append(lista, e)
	}
	if err := filas.Err(); err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, lista)
}

type EventoSenamhi struct {
	Fecha        string          `json:"fecha"`
	Codigo       string          `json:"codigo"`
	Estacion     string          `json:"estacion"`
	Distrito     string          `json:"distrito"`
	Lat          float64         `json:"lat"`
	Lon          float64         `json:"lon"`
	MM           float64         `json:"mm"`
	HorasLluvia  int             `json:"horas_lluvia"`
	MaxHoraMM    float64         `json:"max_hora_mm"`
	HorasConDato int             `json:"horas_con_dato"`
	Nisar        []PasadaCercana `json:"nisar"`
}

func (a *App) listarLluviasSenamhi(w http.ResponseWriter, r *http.Request, s *Sesion) {
	q := r.URL.Query()
	zona := a.cfg.Zona
	desde, hasta := q.Get("desde"), q.Get("hasta")
	d0, err0 := time.ParseInLocation("2006-01-02", desde, zona)
	d1, err1 := time.ParseInLocation("2006-01-02", hasta, zona)
	switch {
	case err0 != nil || err1 != nil:
		responderError(w, http.StatusBadRequest, "Las fechas no son válidas")
		return
	case desde < inicioSenamhi:
		responderError(w, http.StatusBadRequest, "Elige una fecha inicial desde el 01/01/2024")
		return
	case d0.After(d1):
		responderError(w, http.StatusBadRequest, "La fecha inicial debe ser anterior a la final")
		return
	case d1.Sub(d0) > maxDiasRango*24*time.Hour:
		responderError(w, http.StatusBadRequest, "El rango máximo es de un año")
		return
	}
	minimo := 0.1
	if texto := q.Get("minimo"); texto != "" {
		v, err := strconv.ParseFloat(strings.ReplaceAll(texto, ",", "."), 64)
		if err != nil || v < 0.1 || v > 500 {
			responderError(w, http.StatusBadRequest, "La lluvia mínima debe estar entre 0.1 y 500 mm")
			return
		}
		minimo = v
	}
	codigo := q.Get("estacion")

	ctx := r.Context()
	consulta, err := a.db.Query(ctx, `SELECT to_char(l.hora::date, 'YYYY-MM-DD') AS dia, e.codigo, e.nombre, e.distrito, e.lat, e.lon,
			sum(l.mm)::float8, count(*) FILTER (WHERE l.mm > 0), max(l.mm)::float8, count(l.mm)
		FROM lluvia_senamhi l JOIN estaciones_senamhi e ON e.codigo = l.estacion
		WHERE l.hora >= $1::date AND l.hora < $2::date + 1 AND ($3 = '' OR e.codigo = $3)
		GROUP BY dia, e.codigo
		HAVING sum(l.mm) >= $4 - 1e-6
		ORDER BY dia DESC, sum(l.mm) DESC`, desde, hasta, codigo, minimo)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	eventos := []EventoSenamhi{}
	for consulta.Next() {
		var ev EventoSenamhi
		if err := consulta.Scan(&ev.Fecha, &ev.Codigo, &ev.Estacion, &ev.Distrito, &ev.Lat, &ev.Lon, &ev.MM, &ev.HorasLluvia,
			&ev.MaxHoraMM, &ev.HorasConDato); err != nil {
			consulta.Close()
			a.errorInterno(w, err)
			return
		}
		ev.MM, ev.MaxHoraMM = math.Round(ev.MM*10)/10, math.Round(ev.MaxHoraMM*10)/10
		ev.Nisar = []PasadaCercana{}
		eventos = append(eventos, ev)
	}
	consulta.Close()
	if err := consulta.Err(); err != nil {
		a.errorInterno(w, err)
		return
	}

	res := map[string]any{"desde": desde, "hasta": hasta, "minimo_mm": minimo, "total": len(eventos), "nisar_consultado": false,
		"eventos": eventos}
	if len(eventos) > 0 && hasta >= inicioNisar {
		var ciudades []Ciudad
		vistas := map[string]bool{}
		for _, ev := range eventos {
			if !vistas[ev.Codigo] {
				vistas[ev.Codigo] = true
				ciudades = append(ciudades, Ciudad{Nombre: ev.Codigo, Lat: ev.Lat, Lon: ev.Lon})
			}
		}
		inicio := d0
		if desde < inicioNisar {
			inicio, _ = time.ParseInLocation("2006-01-02", inicioNisar, zona)
		}
		pasadas, fallas := a.pasadasPorCiudad(ctx, []Region{{"Senamhi", ciudades}}, inicio, d1.AddDate(0, 0, 2))
		res["nisar_consultado"] = fallas == 0
		if fallas > 0 {
			res["aviso"] = "No se pudo consultar NISAR (ASF): las pasadas pueden faltar."
		}
		for i := range eventos {
			ev := &eventos[i]
			dia, _ := time.ParseInLocation("2006-01-02", ev.Fecha, zona)
			for _, cual := range []struct{ fecha, nombre string }{{ev.Fecha, "mismo"}, {dia.AddDate(0, 0, 1).Format("2006-01-02"), "siguiente"}} {
				for _, p := range pasadas["Senamhi/"+ev.Codigo] {
					if p.InicioUTC.In(zona).Format("2006-01-02") == cual.fecha {
						ev.Nisar = append(ev.Nisar, PasadaCercana{HoraLocal: p.HoraLocal, Pista: p.Pista, Direccion: p.Direccion, Dia: cual.nombre})
					}
				}
			}
		}
	}
	responderJSON(w, http.StatusOK, res)
}
