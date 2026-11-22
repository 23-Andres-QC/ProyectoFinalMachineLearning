package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
	_ "time/tzdata"
)

func main() {
	cfg, err := cargarConfig()
	if err != nil {
		log.Fatalf("configuración: %v", err)
	}
	ctx, cancelar := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancelar()

	db, err := conectarBD(ctx, cfg.BaseDatos)
	if err != nil {
		log.Fatalf("base de datos: %v", err)
	}
	defer db.Close()
	if err := migrar(ctx, db); err != nil {
		log.Fatalf("migraciones: %v", err)
	}
	if err := crearAdminInicial(ctx, db, cfg); err != nil {
		log.Fatalf("administrador inicial: %v", err)
	}
	if len(os.Args) > 2 && os.Args[1] == "importar-senamhi" {
		if err := importarCarpetaSenamhi(ctx, db, os.Args[2:]); err != nil {
			log.Fatalf("importar Senamhi: %v", err)
		}
		return
	}

	app := nuevaApp(cfg, db)
	go app.procesarCola(ctx)

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           app.rutas(),
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      3 * time.Minute,
		IdleTimeout:       2 * time.Minute,
	}
	go func() {
		<-ctx.Done()
		apagado, listo := context.WithTimeout(context.Background(), 10*time.Second)
		defer listo()
		_ = srv.Shutdown(apagado)
	}()
	log.Printf("HidroSAR backend escuchando en %s", srv.Addr)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
