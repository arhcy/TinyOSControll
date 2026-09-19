//go:build linux

package main

import (
	"context"
	"flag"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"osagent/internal/executor"
)

const sudoBin = "/usr/bin/sudo"

func main() {
	socket := flag.String("socket", "/run/osagent/executor.sock", "unix socket path")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	srv := &executor.Server{
		SocketPath: *socket,
		AllowUID:   os.Getuid(),
		Sysinfo:    executor.DefaultSysinfoSource(),
		Log:        log,
		Commands: map[string]*executor.Command{
			executor.CmdAmdsmi:   {Argv: []string{sudoBin, "/usr/bin/amd-smi", "monitor"}, Timeout: 10 * time.Second},
			executor.CmdPoweroff: {Argv: []string{sudoBin, "/usr/bin/systemctl", "poweroff"}, Timeout: 15 * time.Second},
		},
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := srv.Serve(ctx); err != nil {
		log.Error("serve", "err", err)
		os.Exit(1)
	}
}
