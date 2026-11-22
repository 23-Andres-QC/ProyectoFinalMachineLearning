package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"net/http"
	"regexp"
	"time"

	"github.com/jackc/pgx/v5"
)

type Evaluacion struct {
	ID            int64           `json:"id"`
	UsuarioID     int64           `json:"usuario_id"`
	Usuario       string          `json:"usuario"`
	BBox          [4]float64      `json:"bbox"`
	FechaLluvia   string          `json:"fecha_lluvia"`
	Pasada        json.RawMessage `json:"pasada"`
	Referencias   json.RawMessage `json:"referencias"`
	Estado        string          `json:"estado"`
	Mensaje       string          `json:"mensaje"`
	Metodo        string          `json:"metodo"`
	Modelo        string          `json:"modelo"`
	Charcos       *int32          `json:"charcos"`
	AreaAguaM2    *float64        `json:"area_agua_m2"`
	AguaTotalM2   *float64        `json:"agua_total_m2"` // toda el agua segmentada; nil si no se guardó
	MBDescargados *float64        `json:"mb_descargados"`
	Creado        time.Time       `json:"creado"`
	Iniciado      *time.Time      `json:"iniciado"`
	Terminado     *time.Time      `json:"terminado"`
	Progreso      json.RawMessage `json:"progreso"` // {"pasos": [{clave, texto, estado, detalle, segundos}]} o null
	Resultado     json.RawMessage `json:"resultado,omitempty"`
}

type ResumenEvaluacion struct {
	ID          int64      `json:"id"`
	Usuario     string     `json:"usuario"`
	BBox        [4]float64 `json:"bbox"`
	FechaLluvia string     `json:"fecha_lluvia"`
	HoraPasada  string     `json:"hora_pasada"`
	Pista       int        `json:"pista"`
	Estado      string     `json:"estado"`
	Etapa       string     `json:"etapa"` // el paso en curso (o el que falló), para la tabla de Evaluaciones
	Modelo      string     `json:"modelo"`
	Charcos     *int32     `json:"charcos"`
	AreaAguaM2  *float64   `json:"area_agua_m2"`
	Creado      time.Time  `json:"creado"`
}

// modeloValido: id del catálogo del servicio del modelo (por ejemplo «unet_cambio_ensamble» o «agua_superficial/ml_svm»).
// El servicio comprueba que exista; aquí solo se evita guardar cualquier texto.
var modeloValido = regexp.MustCompile(`^[a-z0-9_-]+(/[a-z0-9_-]+)?$`)

// EvaluacionMapa: una evaluación del historial con sus charcos listos para pintar (polígono, área y un punto interior).
type EvaluacionMapa struct {
	ID           int64           `json:"id"`
	Usuario      string          `json:"usuario"`
	BBox         [4]float64      `json:"bbox"`
	FechaLluvia  string          `json:"fecha_lluvia"`
	HoraPasada   string          `json:"hora_pasada"`
	Estado       string          `json:"estado"`
	Charcos      *int32          `json:"charcos"`
	AreaAguaM2   *float64        `json:"area_agua_m2"`
	AguaTotalM2  *float64        `json:"agua_total_m2"`
	ListaCharcos json.RawMessage `json:"lista_charcos"`
}

const columnasCaja = `ST_XMin(e.area), ST_YMin(e.area), ST_XMax(e.area), ST_YMax(e.area)`

// listarHistorial devuelve todo lo procesado (las evaluaciones del usuario, o todas si es administrador) para mostrarlo
// directamente en el mapa.
func (a *App) listarHistorial(w http.ResponseWriter, r *http.Request, s *Sesion) {
	filas, err := a.db.Query(r.Context(), `
		SELECT e.id, u.nombre, `+columnasCaja+`, e.fecha_lluvia, COALESCE(e.pasada->>'hora_local', ''), e.estado, e.charcos,
		       e.area_agua_m2, e.agua_total_m2,
		       COALESCE((SELECT json_agg(json_build_object(
		           'charco', d.path[1],
		           'area_m2', round(ST_Area(d.geom::geography)),
		           'centro', json_build_array(round(ST_X(ST_PointOnSurface(d.geom))::numeric, 6),
		                                      round(ST_Y(ST_PointOnSurface(d.geom))::numeric, 6)),
		           'geometria', ST_AsGeoJSON(d.geom, 6)::json) ORDER BY d.path[1])
		         FROM ST_Dump(e.resultado) d), '[]'::json)
		FROM evaluaciones e JOIN usuarios u ON u.id = e.usuario_id
		WHERE $1 OR e.usuario_id = $2
		ORDER BY e.creado DESC LIMIT 1000`, s.Rol == rolAdmin, s.ID)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	lista, err := pgx.CollectRows(filas, func(f pgx.CollectableRow) (EvaluacionMapa, error) {
		var e EvaluacionMapa
		var fecha time.Time
		var charcos []byte
		err := f.Scan(&e.ID, &e.Usuario, &e.BBox[0], &e.BBox[1], &e.BBox[2], &e.BBox[3], &fecha, &e.HoraPasada, &e.Estado,
			&e.Charcos, &e.AreaAguaM2, &e.AguaTotalM2, &charcos)
		e.FechaLluvia = fecha.Format("2006-01-02")
		e.ListaCharcos = charcos
		return e, err
	})
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, lista)
}

func (a *App) crearEvaluacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	var datos struct {
		BusquedaID string `json:"busqueda_id"`
		Indice     int    `json:"indice"`
		Modelo     string `json:"modelo"`
	}
	if err := leerJSON(w, r, &datos); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	if datos.Modelo != "" && (len(datos.Modelo) > 120 || !modeloValido.MatchString(datos.Modelo)) {
		responderError(w, http.StatusBadRequest, "Modelo inválido")
		return
	}
	busqueda, ok := a.busquedas.obtener(datos.BusquedaID, s.ID)
	if !ok {
		responderError(w, http.StatusGone, "La búsqueda expiró. Vuelve a buscar la fecha en NISAR.")
		return
	}
	if datos.Indice < 0 || datos.Indice >= len(busqueda.Pasadas) {
		responderError(w, http.StatusBadRequest, "La pasada elegida no existe")
		return
	}
	p := busqueda.Pasadas[datos.Indice]
	pasada, err := json.Marshal(p.Pasada)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	referencias, err := json.Marshal(p.Referencias)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	fecha, _ := time.Parse("2006-01-02", busqueda.Fecha)
	b := busqueda.BBox
	var id int64
	err = a.db.QueryRow(r.Context(), `
		INSERT INTO evaluaciones (usuario_id, area, fecha_lluvia, pasada, referencias, modelo)
		VALUES ($1, ST_MakeEnvelope($2, $3, $4, $5, 4326), $6, $7, $8, $9) RETURNING id`,
		s.ID, b[0], b[1], b[2], b[3], fecha, pasada, referencias, datos.Modelo).Scan(&id)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	a.avisarCola()
	responderJSON(w, http.StatusCreated, map[string]int64{"id": id})
}

func (a *App) listarEvaluaciones(w http.ResponseWriter, r *http.Request, s *Sesion) {
	filas, err := a.db.Query(r.Context(), `
		SELECT e.id, u.nombre, `+columnasCaja+`, e.fecha_lluvia, COALESCE(e.pasada->>'hora_local', ''),
		       COALESCE((e.pasada->>'pista')::int, 0), e.estado,
		       CASE WHEN e.estado IN ('procesando', 'error') THEN COALESCE((
		           SELECT p->>'texto' FROM jsonb_array_elements(e.progreso->'pasos') p
		           WHERE p->>'estado' IN ('en_curso', 'error') LIMIT 1), '') ELSE '' END,
		       e.modelo, e.charcos, e.area_agua_m2, e.creado
		FROM evaluaciones e JOIN usuarios u ON u.id = e.usuario_id
		WHERE $1 OR e.usuario_id = $2
		ORDER BY e.creado DESC LIMIT 300`, s.Rol == rolAdmin, s.ID)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	lista, err := pgx.CollectRows(filas, func(f pgx.CollectableRow) (ResumenEvaluacion, error) {
		var e ResumenEvaluacion
		var fecha time.Time
		err := f.Scan(&e.ID, &e.Usuario, &e.BBox[0], &e.BBox[1], &e.BBox[2], &e.BBox[3], &fecha, &e.HoraPasada,
			&e.Pista, &e.Estado, &e.Etapa, &e.Modelo, &e.Charcos, &e.AreaAguaM2, &e.Creado)
		e.FechaLluvia = fecha.Format("2006-01-02")
		return e, err
	})
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, lista)
}

// cargarEvaluacion devuelve la evaluación si existe y el usuario puede verla (la suya, o cualquiera si es administrador).
func (a *App) cargarEvaluacion(r *http.Request, s *Sesion) (*Evaluacion, int, string) {
	id, ok := idDeRuta(r)
	if !ok {
		return nil, http.StatusBadRequest, "Evaluación inválida"
	}
	e := &Evaluacion{}
	var fecha time.Time
	var pasada, referencias, progreso []byte
	err := a.db.QueryRow(r.Context(), `
		SELECT e.id, e.usuario_id, u.nombre, `+columnasCaja+`, e.fecha_lluvia, e.pasada, e.referencias, e.estado,
		       e.mensaje, e.metodo, e.modelo, e.charcos, e.area_agua_m2, e.agua_total_m2, e.mb_descargados, e.creado, e.iniciado,
		       e.terminado, e.progreso
		FROM evaluaciones e JOIN usuarios u ON u.id = e.usuario_id WHERE e.id = $1`, id).
		Scan(&e.ID, &e.UsuarioID, &e.Usuario, &e.BBox[0], &e.BBox[1], &e.BBox[2], &e.BBox[3], &fecha, &pasada, &referencias,
			&e.Estado, &e.Mensaje, &e.Metodo, &e.Modelo, &e.Charcos, &e.AreaAguaM2, &e.AguaTotalM2, &e.MBDescargados, &e.Creado,
			&e.Iniciado, &e.Terminado, &progreso)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && s.Rol != rolAdmin && e.UsuarioID != s.ID) {
		return nil, http.StatusNotFound, "La evaluación no existe"
	}
	if err != nil {
		return nil, http.StatusInternalServerError, err.Error()
	}
	e.FechaLluvia = fecha.Format("2006-01-02")
	e.Pasada, e.Referencias = pasada, referencias
	if progreso != nil {
		e.Progreso = progreso
	}
	return e, 0, ""
}

// charcosGeoJSON: los charcos como FeatureCollection. Con conAgua, la descarga lleva primero toda el agua segmentada
// (propiedad capa = agua_segmentada), para que en un SIG quede debajo de los charcos.
func (a *App) charcosGeoJSON(r *http.Request, id int64, conAgua bool) (json.RawMessage, error) {
	var features []byte
	err := a.db.QueryRow(r.Context(), `
		SELECT COALESCE(json_agg(t.f ORDER BY t.orden), '[]'::json) FROM (
		  SELECT 0 AS orden, json_build_object('type', 'Feature',
		           'properties', json_build_object('capa', 'agua_segmentada', 'area_m2', round(e.agua_total_m2)),
		           'geometry', ST_AsGeoJSON(e.agua, 6)::json) AS f
		  FROM evaluaciones e WHERE e.id = $1 AND $2 AND e.agua IS NOT NULL
		  UNION ALL
		  SELECT d.path[1], json_build_object(
		           'type', 'Feature',
		           'properties', json_build_object('charco', d.path[1], 'area_m2', round(ST_Area(d.geom::geography))),
		           'geometry', ST_AsGeoJSON(d.geom, 6)::json)
		  FROM evaluaciones e, ST_Dump(e.resultado) d WHERE e.id = $1) t`, id, conAgua).Scan(&features)
	if err != nil {
		return nil, err
	}
	return json.RawMessage(fmt.Sprintf(`{"type":"FeatureCollection","features":%s}`, features)), nil
}

// verAgua: toda el agua que segmentó el modelo ese día, como un Feature (o null si no se guardó). El mapa la pide aparte
// porque puede pesar más que los charcos (mar, ríos), y solo cuando se dibuja la evaluación.
func (a *App) verAgua(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	var feature []byte
	err := a.db.QueryRow(r.Context(), `
		SELECT json_build_object('type', 'Feature',
		         'properties', json_build_object('area_m2', round(agua_total_m2)),
		         'geometry', ST_AsGeoJSON(agua, 6)::json)
		FROM evaluaciones WHERE id = $1 AND agua IS NOT NULL`, e.ID).Scan(&feature)
	if errors.Is(err, pgx.ErrNoRows) {
		feature, err = []byte("null"), nil
	}
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, json.RawMessage(feature))
}

func (a *App) verEvaluacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	if e.Estado == "completado" {
		resultado, err := a.charcosGeoJSON(r, e.ID, false)
		if err != nil {
			a.errorInterno(w, err)
			return
		}
		e.Resultado = resultado
	}
	responderJSON(w, http.StatusOK, e)
}

func (a *App) descargarGeoJSON(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	resultado, err := a.charcosGeoJSON(r, e.ID, true)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	w.Header().Set("Content-Type", "application/geo+json")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="hidrosar_%d_%s.geojson"`, e.ID, e.FechaLluvia))
	_, _ = w.Write(resultado)
}

func (a *App) descargarKML(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	var area, agua, charcos string
	err := a.db.QueryRow(r.Context(), `
		SELECT ST_AsKML(e.area, 6),
		       CASE WHEN e.agua IS NULL THEN '' ELSE format(
		           '<Placemark><name>Agua segmentada</name><description>%s m²</description><styleUrl>#agua</styleUrl>%s</Placemark>',
		           round(e.agua_total_m2), ST_AsKML(e.agua, 6)) END,
		       COALESCE((SELECT string_agg(format(
		           '<Placemark><name>Charco %s</name><description>%s m²</description><styleUrl>#charco</styleUrl>%s</Placemark>',
		           d.path[1], round(ST_Area(d.geom::geography)), ST_AsKML(d.geom, 6)), '' ORDER BY d.path[1])
		         FROM ST_Dump(e.resultado) d), '')
		FROM evaluaciones e WHERE e.id = $1`, e.ID).Scan(&area, &agua, &charcos)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	titulo := html.EscapeString(fmt.Sprintf("HidroSAR %d · lluvia del %s", e.ID, e.FechaLluvia))
	w.Header().Set("Content-Type", "application/vnd.google-earth.kml+xml")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="hidrosar_%d_%s.kml"`, e.ID, e.FechaLluvia))
	_, _ = fmt.Fprintf(w, `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>%s</name>
<Style id="area"><LineStyle><color>ff00ffff</color><width>2</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>
<Style id="agua"><LineStyle><color>ffff6f1f</color><width>1</width></LineStyle><PolyStyle><color>70ff6f1f</color></PolyStyle></Style>
<Style id="charco"><LineStyle><color>ff2b1de0</color><width>1</width></LineStyle><PolyStyle><color>a02b1de0</color></PolyStyle></Style>
<Placemark><name>Área evaluada</name><styleUrl>#area</styleUrl>%s</Placemark>
%s
%s
</Document></kml>
`, titulo, area, agua, charcos)
}

func (a *App) eliminarEvaluacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	if _, err := a.db.Exec(r.Context(), `DELETE FROM evaluaciones WHERE id = $1`, e.ID); err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

// reintentarEvaluacion vuelve a poner en cola una evaluación con error (por ejemplo, si faltaba el modelo o las
// credenciales): se reusan el área, la pasada y las referencias guardadas, sin volver a buscar en NISAR.
func (a *App) reintentarEvaluacion(w http.ResponseWriter, r *http.Request, s *Sesion) {
	e, codigo, mensaje := a.cargarEvaluacion(r, s)
	if e == nil {
		a.responderFallo(w, codigo, mensaje)
		return
	}
	etiqueta, err := a.db.Exec(r.Context(), `UPDATE evaluaciones SET estado = 'en_cola', mensaje = '', iniciado = NULL, terminado = NULL,
		progreso = NULL WHERE id = $1 AND estado = 'error'`, e.ID)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if etiqueta.RowsAffected() == 0 {
		responderError(w, http.StatusConflict, "Solo se puede reintentar una evaluación que terminó con error")
		return
	}
	a.avisarCola()
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (a *App) responderFallo(w http.ResponseWriter, codigo int, mensaje string) {
	if codigo == http.StatusInternalServerError {
		a.errorInterno(w, errors.New(mensaje))
		return
	}
	responderError(w, codigo, mensaje)
}
