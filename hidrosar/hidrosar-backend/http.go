package main

import (
	"encoding/json"
	"errors"
	"log"
	"mime"
	"net/http"
	"strconv"
	"time"
)

func responderJSON(w http.ResponseWriter, codigo int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(codigo)
	if v != nil {
		_ = json.NewEncoder(w).Encode(v)
	}
}

func responderError(w http.ResponseWriter, codigo int, mensaje string) {
	responderJSON(w, codigo, map[string]string{"error": mensaje})
}

var errNoJSON = errors.New("se esperaba un cuerpo JSON")

func leerJSON(w http.ResponseWriter, r *http.Request, v any) error {
	tipo, _, _ := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if tipo != "application/json" {
		return errNoJSON
	}
	return json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(v)
}

func idDeRuta(r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	return id, err == nil && id > 0
}

type grabador struct {
	http.ResponseWriter
	codigo int
}

func (g *grabador) WriteHeader(codigo int) {
	g.codigo = codigo
	g.ResponseWriter.WriteHeader(codigo)
}

func registrar(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		inicio := time.Now()
		g := &grabador{ResponseWriter: w, codigo: http.StatusOK}
		h.ServeHTTP(g, r)
		log.Printf("%s %s %d %s", r.Method, r.URL.Path, g.codigo, time.Since(inicio).Round(time.Millisecond))
	})
}
