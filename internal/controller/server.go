package controller

import (
	"context"
	"crypto/subtle"
	"crypto/tls"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"regexp"
	"strings"
	"sync"
	"time"

	"nhooyr.io/websocket"

	"osagent/internal/config"
	"osagent/internal/protocol"
	"osagent/internal/telemetry"
	"osagent/internal/tlsutil"
	"osagent/internal/wol"
)

//go:embed web
var webFS embed.FS

var containerNameRe = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)

var contentTypes = map[string]string{
	"index.html": "text/html; charset=utf-8",
	"app.js":     "application/javascript; charset=utf-8",
	"style.css":  "text/css; charset=utf-8",
}

// Server is the controller: web panel + management channel + telemetry store.
type Server struct {
	cfg     *config.ControllerConfig
	log     *slog.Logger
	hub     *Hub
	store   *telemetry.Store
	agent   *AgentClient
	wolMac  net.HardwareAddr
	wolIP   string
	limiter *RateLimiter
	wsTLS   *tls.Config
	webTLS  *tls.Config

	mu         sync.Mutex
	containers []protocol.ContainerInfo
}

func NewServer(cfg *config.ControllerConfig, log *slog.Logger) (*Server, error) {
	mac, err := wol.ParseMAC(cfg.WoL.MAC)
	if err != nil {
		return nil, err
	}
	caPool, err := tlsutil.LoadCA(cfg.TLS.CA)
	if err != nil {
		return nil, err
	}
	cert, err := tlsutil.LoadCert(cfg.TLS.Cert, cfg.TLS.Key)
	if err != nil {
		return nil, err
	}
	s := &Server{
		cfg:     cfg,
		log:     log,
		hub:     NewHub(),
		store:   telemetry.NewStore(cfg.Telemetry.HistoryMinutes * 60),
		wolMac:  mac,
		wolIP:   cfg.WoL.IP,
		limiter: NewRateLimiter(10, 6*time.Second),
		wsTLS:   tlsutil.ServerConfig(cert, caPool),
		webTLS:  &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{cert}},
	}
	s.agent = NewAgentClient(log, s.hub, s.store)
	return s, nil
}

func (s *Server) Run(ctx context.Context) error {
	go s.agent.Run(ctx)
	go s.pollContainers(ctx)
	errCh := make(chan error, 2)
	go func() { errCh <- s.serveWeb(ctx) }()
	go func() { errCh <- s.serveManagement(ctx) }()
	select {
	case <-ctx.Done():
		return nil
	case err := <-errCh:
		return err
	}
}

func (s *Server) serveWeb(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleWeb)
	mux.HandleFunc("/api/status", s.handleStatus)
	mux.HandleFunc("/api/events", s.handleEvents)
	mux.HandleFunc("/api/actions", s.handleActions)
	srv := &http.Server{Addr: s.cfg.Listen.Web, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	ln, err := net.Listen("tcp", s.cfg.Listen.Web)
	if err != nil {
		return err
	}
	go func() {
		<-ctx.Done()
		srv.Close()
	}()
	s.log.Info("web listening", "addr", s.cfg.Listen.Web)
	return srv.Serve(tls.NewListener(ln, s.webTLS))
}

func (s *Server) serveManagement(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", s.handleWS)
	srv := &http.Server{Addr: s.cfg.Listen.Management, Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	ln, err := net.Listen("tcp", s.cfg.Listen.Management)
	if err != nil {
		return err
	}
	go func() {
		<-ctx.Done()
		srv.Close()
	}()
	s.log.Info("management listening", "addr", s.cfg.Listen.Management)
	return srv.Serve(tls.NewListener(ln, s.wsTLS))
}

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := websocket.Accept(w, r, nil)
	if err != nil {
		return
	}
	s.agent.Accept(conn)
}

func (s *Server) handleWeb(w http.ResponseWriter, r *http.Request) {
	name := strings.TrimPrefix(r.URL.Path, "/")
	if name == "" {
		name = "index.html"
	}
	ct, ok := contentTypes[name]
	if !ok {
		http.NotFound(w, r)
		return
	}
	data, err := webFS.ReadFile("web/" + name)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", ct)
	_, _ = w.Write(data)
}

func (s *Server) authOK(r *http.Request) bool {
	key := r.Header.Get("X-API-Key")
	if key == "" {
		key = r.URL.Query().Get("key")
	}
	return subtle.ConstantTimeCompare([]byte(key), []byte(s.cfg.APIToken)) == 1
}

func (s *Server) statusSnapshot() map[string]any {
	latest, _ := s.store.Latest()
	s.mu.Lock()
	containers := s.containers
	s.mu.Unlock()
	return map[string]any{
		"agent_online": s.agent.Online(),
		"wol_mac":      s.cfg.WoL.MAC,
		"containers":   containers,
		"telemetry":    latest,
	}
}

func (s *Server) handleStatus(w http.ResponseWriter, r *http.Request) {
	if !s.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(s.statusSnapshot())
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	if !s.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming unsupported", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher.Flush()
	ch, cancel := s.hub.Subscribe()
	defer cancel()
	snap, _ := json.Marshal(s.statusSnapshot())
	fmt.Fprintf(w, "event: status\ndata: %s\n\n", snap)
	flusher.Flush()
	keepalive := time.NewTicker(30 * time.Second)
	defer keepalive.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case ev := <-ch:
			fmt.Fprintf(w, "event: %s\ndata: %s\n\n", ev.event, ev.data)
			flusher.Flush()
		case <-keepalive.C:
			fmt.Fprint(w, ": ping\n\n")
			flusher.Flush()
		}
	}
}

type actionRequest struct {
	Action string `json:"action"`
	Name   string `json:"name"`
	Op     string `json:"op"`
}

func (s *Server) handleActions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !s.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	ip := clientIP(r)
	if !s.limiter.Allow(ip) {
		http.Error(w, "rate limited", http.StatusTooManyRequests)
		return
	}
	var req actionRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<10)).Decode(&req); err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}
	start := time.Now()
	var err error
	switch req.Action {
	case "wol":
		sender := &wol.Sender{Port: s.cfg.WoL.Port}
		err = sender.Send(r.Context(), s.wolMac, s.wolIP)
	case "shutdown":
		_, err = s.agent.Request(r.Context(), protocol.ActionShutdown, nil)
	case "container":
		if !containerNameRe.MatchString(req.Name) {
			http.Error(w, "invalid container name", http.StatusBadRequest)
			return
		}
		switch req.Op {
		case "start", "stop", "restart":
		default:
			http.Error(w, "invalid op", http.StatusBadRequest)
			return
		}
		_, err = s.agent.Request(r.Context(), protocol.ActionContainerAction,
			protocol.ContainerActionPayload{Name: req.Name, Action: req.Op})
	default:
		http.Error(w, "unknown action", http.StatusBadRequest)
		return
	}
	s.log.Info("action", "action", req.Action, "name", req.Name, "op", req.Op,
		"ip", ip, "ok", err == nil, "err", err, "dur_ms", time.Since(start).Milliseconds())
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"ok": true})
}

func (s *Server) pollContainers(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
		if !s.agent.Online() {
			continue
		}
		rctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		payload, err := s.agent.Request(rctx, protocol.ActionContainersList, nil)
		cancel()
		if err != nil {
			continue
		}
		var cl protocol.ContainerListPayload
		if err := json.Unmarshal(payload, &cl); err != nil {
			continue
		}
		s.mu.Lock()
		s.containers = cl.Containers
		s.mu.Unlock()
		data, _ := json.Marshal(cl)
		s.hub.Publish("containers", data)
	}
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}
