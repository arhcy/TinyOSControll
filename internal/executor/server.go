//go:build linux

package executor

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"golang.org/x/sys/unix"
)

// Command is one allowlisted host command (exact argv, no shell).
type Command struct {
	Argv    []string
	Timeout time.Duration
}

// Server is the host-side executor daemon.
type Server struct {
	SocketPath string
	AllowUID   int
	Commands   map[string]*Command
	Sysinfo    *SysinfoSource
	Log        *slog.Logger
}

func (s *Server) Serve(ctx context.Context) error {
	if s.Log == nil {
		s.Log = slog.Default()
	}
	if err := os.MkdirAll(filepath.Dir(s.SocketPath), 0o750); err != nil {
		return fmt.Errorf("mkdir socket dir: %w", err)
	}
	_ = os.Remove(s.SocketPath)
	ln, err := net.Listen("unix", s.SocketPath)
	if err != nil {
		return fmt.Errorf("listen: %w", err)
	}
	os.Chmod(s.SocketPath, 0o660)
	s.Log.Info("executor listening", "socket", s.SocketPath, "allow_uid", s.AllowUID)
	go func() {
		<-ctx.Done()
		ln.Close()
	}()
	for {
		conn, err := ln.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			continue
		}
		go s.handle(conn)
	}
}

func (s *Server) handle(conn net.Conn) {
	defer conn.Close()
	cred, err := peerCredentials(conn)
	if err != nil || int(cred.Uid) != s.AllowUID {
		s.Log.Warn("rejected connection", "err", err)
		return
	}
	conn.SetDeadline(time.Now().Add(60 * time.Second))
	r := bufio.NewReader(conn)
	for {
		line, err := r.ReadBytes('\n')
		if err != nil {
			return
		}
		var req Request
		if err := json.Unmarshal(line, &req); err != nil {
			s.writeResponse(conn, Response{OK: false, Error: "bad request"})
			continue
		}
		s.writeResponse(conn, s.dispatch(req))
	}
}

func (s *Server) writeResponse(conn net.Conn, resp Response) {
	b, _ := json.Marshal(resp)
	_, _ = conn.Write(append(b, '\n'))
}

func (s *Server) dispatch(req Request) Response {
	switch req.Cmd {
	case CmdSysinfo:
		d, err := s.Sysinfo.Collect()
		if err != nil {
			return Response{OK: false, Error: err.Error()}
		}
		data, _ := json.Marshal(d)
		return Response{OK: true, Data: data}
	case CmdAmdsmi, CmdPoweroff:
		c, ok := s.Commands[req.Cmd]
		if !ok {
			return Response{OK: false, Error: "unknown command"}
		}
		out, err := runCommand(c)
		if err != nil {
			return Response{OK: false, Error: err.Error()}
		}
		data, _ := json.Marshal(AmdsmiData{Raw: out})
		return Response{OK: true, Data: data}
	default:
		return Response{OK: false, Error: "unknown command"}
	}
}

func runCommand(c *Command) (string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), c.Timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.Argv[0], c.Argv[1:]...)
	out, err := cmd.CombinedOutput()
	if ctx.Err() == context.DeadlineExceeded {
		return string(out), fmt.Errorf("command timed out")
	}
	return string(out), err
}

// peerCredentials returns the SO_PEERCRED identity of the unix-socket peer.
func peerCredentials(conn net.Conn) (*unix.Ucred, error) {
	uc, ok := conn.(*net.UnixConn)
	if !ok {
		return nil, errors.New("not a unix conn")
	}
	sc, err := uc.SyscallConn()
	if err != nil {
		return nil, err
	}
	var cred *unix.Ucred
	_ = sc.Control(func(fd uintptr) {
		c, e := unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
		if e != nil {
			err = e
			return
		}
		cred = c
	})
	return cred, err
}
