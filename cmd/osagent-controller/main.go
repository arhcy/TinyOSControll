package main

import (
	"context"
	"flag"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"osagent/internal/config"
	"osagent/internal/controller"
)

func main() {
	cfgPath := flag.String("config", "/etc/osagent/controller.yaml", "path to controller config")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.LoadController(*cfgPath)
	if err != nil {
		log.Error("config", "err", err)
		os.Exit(1)
	}
	srv, err := controller.NewServer(cfg, log)
	if err != nil {
		log.Error("init", "err", err)
		os.Exit(1)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := srv.Run(ctx); err != nil {
		log.Error("run", "err", err)
		os.Exit(1)
	}
}
