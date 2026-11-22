package main

import (
	"context"
	"embed"
	"io/fs"
	"log"
	"sort"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

//go:embed migraciones/*.sql
var migraciones embed.FS

func conectarBD(ctx context.Context, url string) (*pgxpool.Pool, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 10
	for intento := 1; ; intento++ {
		pool, err := pgxpool.NewWithConfig(ctx, cfg)
		if err == nil {
			if err = pool.Ping(ctx); err == nil {
				return pool, nil
			}
			pool.Close()
		}
		if intento == 30 {
			return nil, err
		}
		log.Printf("esperando la base de datos (%d): %v", intento, err)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}
}

func migrar(ctx context.Context, db *pgxpool.Pool) error {
	if _, err := db.Exec(ctx, `CREATE TABLE IF NOT EXISTS migraciones (
		nombre TEXT PRIMARY KEY, aplicada TIMESTAMPTZ NOT NULL DEFAULT now())`); err != nil {
		return err
	}
	archivos, err := fs.Glob(migraciones, "migraciones/*.sql")
	if err != nil {
		return err
	}
	sort.Strings(archivos)
	for _, archivo := range archivos {
		var aplicada bool
		if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM migraciones WHERE nombre = $1)`, archivo).Scan(&aplicada); err != nil {
			return err
		}
		if aplicada {
			continue
		}
		sql, err := migraciones.ReadFile(archivo)
		if err != nil {
			return err
		}
		tx, err := db.Begin(ctx)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, string(sql)); err != nil {
			_ = tx.Rollback(ctx)
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO migraciones (nombre) VALUES ($1)`, archivo); err != nil {
			_ = tx.Rollback(ctx)
			return err
		}
		if err := tx.Commit(ctx); err != nil {
			return err
		}
		log.Printf("migración aplicada: %s", archivo)
	}
	return nil
}

func crearAdminInicial(ctx context.Context, db *pgxpool.Pool, cfg Config) error {
	var usuarios int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM usuarios`).Scan(&usuarios); err != nil {
		return err
	}
	if usuarios > 0 {
		return nil
	}
	if cfg.AdminEmail == "" || len(cfg.AdminClave) < 8 {
		return errNoAdmin
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(cfg.AdminClave), costoBcrypt)
	if err != nil {
		return err
	}
	_, err = db.Exec(ctx, `INSERT INTO usuarios (nombre, email, clave_hash, rol) VALUES ($1, $2, $3, $4)`,
		cfg.AdminNombre, cfg.AdminEmail, string(hash), rolAdmin)
	if err == nil {
		log.Printf("administrador inicial creado: %s", cfg.AdminEmail)
	}
	return err
}
