package main

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"golang.org/x/crypto/bcrypt"
)

const (
	rolAdmin     = "administrador"
	rolEvaluador = "evaluador"
)

type Usuario struct {
	ID           int64      `json:"id"`
	Nombre       string     `json:"nombre"`
	Email        string     `json:"email"`
	Rol          string     `json:"rol"`
	Activo       bool       `json:"activo"`
	Creado       time.Time  `json:"creado"`
	UltimoAcceso *time.Time `json:"ultimo_acceso"`
	Evaluaciones int        `json:"evaluaciones"`
}

type datosUsuario struct {
	Nombre string `json:"nombre"`
	Email  string `json:"email"`
	Rol    string `json:"rol"`
	Clave  string `json:"clave"`
	Activo *bool  `json:"activo"`
}

func (d *datosUsuario) validar(claveObligatoria bool) string {
	d.Nombre, d.Email = strings.TrimSpace(d.Nombre), normalizarEmail(d.Email)
	switch {
	case d.Nombre == "" || len(d.Nombre) > 100:
		return "El nombre es obligatorio (hasta 100 caracteres)"
	case !strings.Contains(d.Email, "@") || len(d.Email) > 200:
		return "El correo no es válido"
	case d.Rol != rolAdmin && d.Rol != rolEvaluador:
		return "El rol debe ser administrador o evaluador"
	case (claveObligatoria || d.Clave != "") && len(d.Clave) < 8:
		return "La contraseña debe tener al menos 8 caracteres"
	}
	return ""
}

func esDuplicado(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}

func (a *App) listarUsuarios(w http.ResponseWriter, r *http.Request, s *Sesion) {
	filas, err := a.db.Query(r.Context(), `
		SELECT u.id, u.nombre, u.email, u.rol, u.activo, u.creado, u.ultimo_acceso, count(e.id)
		FROM usuarios u LEFT JOIN evaluaciones e ON e.usuario_id = u.id
		GROUP BY u.id ORDER BY u.nombre`)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	usuarios, err := pgx.CollectRows(filas, func(f pgx.CollectableRow) (Usuario, error) {
		var u Usuario
		err := f.Scan(&u.ID, &u.Nombre, &u.Email, &u.Rol, &u.Activo, &u.Creado, &u.UltimoAcceso, &u.Evaluaciones)
		return u, err
	})
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusOK, usuarios)
}

func (a *App) crearUsuario(w http.ResponseWriter, r *http.Request, s *Sesion) {
	var d datosUsuario
	if err := leerJSON(w, r, &d); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	if problema := d.validar(true); problema != "" {
		responderError(w, http.StatusBadRequest, problema)
		return
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(d.Clave), costoBcrypt)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	activo := d.Activo == nil || *d.Activo
	var id int64
	err = a.db.QueryRow(r.Context(), `INSERT INTO usuarios (nombre, email, clave_hash, rol, activo)
		VALUES ($1, $2, $3, $4, $5) RETURNING id`, d.Nombre, d.Email, string(hash), d.Rol, activo).Scan(&id)
	if esDuplicado(err) {
		responderError(w, http.StatusConflict, "Ya existe un usuario con ese correo")
		return
	}
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	responderJSON(w, http.StatusCreated, map[string]int64{"id": id})
}

func (a *App) editarUsuario(w http.ResponseWriter, r *http.Request, s *Sesion) {
	id, ok := idDeRuta(r)
	if !ok {
		responderError(w, http.StatusBadRequest, "Usuario inválido")
		return
	}
	var d datosUsuario
	if err := leerJSON(w, r, &d); err != nil {
		responderError(w, http.StatusBadRequest, "Datos inválidos")
		return
	}
	if problema := d.validar(false); problema != "" {
		responderError(w, http.StatusBadRequest, problema)
		return
	}
	activo := d.Activo == nil || *d.Activo
	if id == s.ID && (d.Rol != rolAdmin || !activo) {
		responderError(w, http.StatusBadRequest, "No puedes quitarte el rol de administrador ni desactivar tu propio usuario")
		return
	}
	etiqueta, err := a.db.Exec(r.Context(), `UPDATE usuarios SET nombre = $2, email = $3, rol = $4, activo = $5 WHERE id = $1`,
		id, d.Nombre, d.Email, d.Rol, activo)
	if esDuplicado(err) {
		responderError(w, http.StatusConflict, "Ya existe un usuario con ese correo")
		return
	}
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if etiqueta.RowsAffected() == 0 {
		responderError(w, http.StatusNotFound, "El usuario no existe")
		return
	}
	if d.Clave != "" {
		hash, err := bcrypt.GenerateFromPassword([]byte(d.Clave), costoBcrypt)
		if err != nil {
			a.errorInterno(w, err)
			return
		}
		if _, err := a.db.Exec(r.Context(), `UPDATE usuarios SET clave_hash = $2 WHERE id = $1`, id, string(hash)); err != nil {
			a.errorInterno(w, err)
			return
		}
	}
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (a *App) eliminarUsuario(w http.ResponseWriter, r *http.Request, s *Sesion) {
	id, ok := idDeRuta(r)
	if !ok {
		responderError(w, http.StatusBadRequest, "Usuario inválido")
		return
	}
	if id == s.ID {
		responderError(w, http.StatusBadRequest, "No puedes eliminar tu propio usuario")
		return
	}
	etiqueta, err := a.db.Exec(r.Context(), `DELETE FROM usuarios WHERE id = $1`, id)
	if err != nil {
		a.errorInterno(w, err)
		return
	}
	if etiqueta.RowsAffected() == 0 {
		responderError(w, http.StatusNotFound, "El usuario no existe")
		return
	}
	responderJSON(w, http.StatusOK, map[string]bool{"ok": true})
}
