package main

import (
	"context"
	"errors"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5"
	"golang.org/x/crypto/bcrypt"
)

const (
	nombreCookie = "hidrosar_sesion"
	costoBcrypt  = 12
	emisor       = "hidrosar"
)

var (
	errNoAdmin     = errors.New("define ADMIN_EMAIL y ADMIN_PASSWORD (8 caracteres o más) en el .env")
	errDesactivado = errors.New("usuario desactivado")
	hashFalso, _   = bcrypt.GenerateFromPassword([]byte("hidrosar-usuario-inexistente"), bcrypt.MinCost)
)

type Sesion struct {
	ID     int64  `json:"id"`
	Nombre string `json:"nombre"`
	Email  string `json:"email"`
	Rol    string `json:"rol"`
}

type manejador func(http.ResponseWriter, *http.Request, *Sesion)

func (a *App) conSesion(h manejador) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s, err := a.leerSesion(r)
		if err != nil {
			responderError(w, http.StatusUnauthorized, "Inicia sesión para continuar")
			return
		}
		h(w, r, s)
	})
}

func (a *App) soloAdmin(h manejador) http.Handler {
	return a.conSesion(func(w http.ResponseWriter, r *http.Request, s *Sesion) {
		if s.Rol != rolAdmin {
			responderError(w, http.StatusForbidden, "Solo un administrador puede hacer esto")
			return
		}
		h(w, r, s)
	})
}

func (a *App) leerSesion(r *http.Request) (*Sesion, error) {
	cookie, err := r.Cookie(nombreCookie)
	if err != nil {
		return nil, err
	}
	claims := &jwt.RegisteredClaims{}
	_, err = jwt.ParseWithClaims(cookie.Value, claims, func(*jwt.Token) (any, error) { return a.cfg.SecretoJWT, nil },
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}), jwt.WithIssuer(emisor), jwt.WithExpirationRequired())
	if err != nil {
		return nil, err
	}
	id, err := strconv.ParseInt(claims.Subject, 10, 64)
	if err != nil {
		return nil, err
	}
	return a.sesionDeUsuario(r.Context(), id)
}

func (a *App) sesionDeUsuario(ctx context.Context, id int64) (*Sesion, error) {
	s := &Sesion{}
	var activo bool
	err := a.db.QueryRow(ctx, `SELECT id, nombre, email, rol, activo FROM usuarios WHERE id = $1`, id).
		Scan(&s.ID, &s.Nombre, &s.Email, &s.Rol, &activo)
	if err != nil {
		return nil, err
	}
	if !activo {
		return nil, errDesactivado
	}
	return s, nil
}

func (a *App) ponerCookie(w http.ResponseWriter, valor string, duracion time.Duration) {
	http.SetCookie(w, &http.Cookie{
		Name: nombreCookie, Value: valor, Path: "/", HttpOnly: true, Secure: a.cfg.CookieSegura,
		SameSite: http.SameSiteStrictMode, MaxAge: int(duracion.Seconds()),
	})
}

func (a *App) login(w http.ResponseWriter, r *http.Request) {
	var datos struct {
		Email string `json:"email"`
		Clave string `json:"clave"`
	}
	if err := leerJSON(w, r, &datos); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	ip := ipCliente(r)
	if !a.limitador.permitir(ip) {
		responderError(w, http.StatusTooManyRequests, "Demasiados intentos. Espera unos minutos.")
		return
	}
	var id int64
	var hash string
	var activo bool
	err := a.db.QueryRow(r.Context(), `SELECT id, clave_hash, activo FROM usuarios WHERE email = $1`,
		normalizarEmail(datos.Email)).Scan(&id, &hash, &activo)
	if errors.Is(err, pgx.ErrNoRows) {
		_ = bcrypt.CompareHashAndPassword(hashFalso, []byte(datos.Clave))
		responderError(w, http.StatusUnauthorized, "Correo o contraseña incorrectos")
		return
	}
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if bcrypt.CompareHashAndPassword([]byte(hash), []byte(datos.Clave)) != nil {
		responderError(w, http.StatusUnauthorized, "Correo o contraseña incorrectos")
		return
	}
	if !activo {
		responderError(w, http.StatusForbidden, "Tu usuario está desactivado. Pide ayuda a un administrador.")
		return
	}
	ahora := time.Now()
	token, err := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.RegisteredClaims{
		Subject: strconv.FormatInt(id, 10), Issuer: emisor, IssuedAt: jwt.NewNumericDate(ahora),
		ExpiresAt: jwt.NewNumericDate(ahora.Add(a.cfg.DuracionSesion)),
	}).SignedString(a.cfg.SecretoJWT)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	a.limitador.reiniciar(ip)
	a.ponerCookie(w, token, a.cfg.DuracionSesion)
	_, _ = a.db.Exec(r.Context(), `UPDATE usuarios SET ultimo_acceso = now() WHERE id = $1`, id)
	s, err := a.sesionDeUsuario(r.Context(), id)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, map[string]any{"usuario": s})
}

func (a *App) logout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{Name: nombreCookie, Value: "", Path: "/", HttpOnly: true, Secure: a.cfg.CookieSegura,
		SameSite: http.SameSiteStrictMode, MaxAge: -1})
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (a *App) yo(w http.ResponseWriter, r *http.Request, s *Sesion) {
	responderJSON(w, http.StatusOK, map[string]any{"usuario": s})
}

func (a *App) cambiarClave(w http.ResponseWriter, r *http.Request, s *Sesion) {
	var datos struct {
		Actual string `json:"actual"`
		Nueva  string `json:"nueva"`
	}
	if err := leerJSON(w, r, &datos); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	if len(datos.Nueva) < 8 {
		responderError(w, http.StatusBadRequest, "La contraseña nueva debe tener al menos 8 caracteres")
		return
	}
	var hash string
	if err := a.db.QueryRow(r.Context(), `SELECT clave_hash FROM usuarios WHERE id = $1`, s.ID).Scan(&hash); err != nil {
		a.errorInterno(w, err)
		return
	}
	if bcrypt.CompareHashAndPassword([]byte(hash), []byte(datos.Actual)) != nil {
		responderError(w, http.StatusBadRequest, "La contraseña actual no es correcta")
		return
	}
	nuevo, err := bcrypt.GenerateFromPassword([]byte(datos.Nueva), costoBcrypt)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if _, err := a.db.Exec(r.Context(), `UPDATE usuarios SET clave_hash = $2 WHERE id = $1`, s.ID, string(nuevo)); err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func ipCliente(r *http.Request) string {
	if ip := strings.TrimSpace(r.Header.Get("X-Real-IP")); ip != "" {
		return ip
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

type limitador struct {
	mu       sync.Mutex
	maximo   int
	ventana  time.Duration
	intentos map[string][]time.Time
}

func nuevoLimitador(maximo int, ventana time.Duration) *limitador {
	return &limitador{maximo: maximo, ventana: ventana, intentos: map[string][]time.Time{}}
}

func (l *limitador) permitir(clave string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	limite := time.Now().Add(-l.ventana)
	recientes := l.intentos[clave][:0]
	for _, t := range l.intentos[clave] {
		if t.After(limite) {
			recientes = append(recientes, t)
		}
	}
	if len(recientes) >= l.maximo {
		l.intentos[clave] = recientes
		return false
	}
	l.intentos[clave] = append(recientes, time.Now())
	return true
}

func (l *limitador) reiniciar(clave string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.intentos, clave)
}
