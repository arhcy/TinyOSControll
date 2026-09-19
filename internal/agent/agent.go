package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"

	"nhooyr.io/websocket"

	"osagent/internal/config"
	"osagent/internal/dockerapi"
	"osagent/internal/executor"
	"osagent/internal/protocol"
	"osagent/internal/tlsutil"
)

const Version = "0.1.0"

var containerNameRe = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)

// Agent runs on the target host and connects outbound to the controller.
type Agent struct {
	cfg     *config.AgentConfig
	log     *slog.Logger
	exec    *executor.Client
	docker  *dockerapi.Client
	http    *http.Client
	allowed map[string]bool
}

func New(cfg *config.AgentConfig, log *slog.Logger) (*Agent, error) {
	caPool, err := tlsutil.LoadCA(cfg.TLS.CA)
	if err != nil {
		return nil, err
	}
	cert, err := tlsutil.LoadCert(cfg.TLS.Cert, cfg.TLS.Key)
	if err != nil {
		return nil, err
	}
	docker, err := dockerapi.NewClient(cfg.Docker.Endpoint)
	if err != nil {
		return nil, err
	}
	u, err := url.Parse(cfg.Controller.URL)
	if err != nil {
		return nil, err
	}
	allowed := make(map[string]bool, len(cfg.Docker.Containers))
	for _, n := range cfg.Docker.Containers {
		allowed[n] = true
	}
	return &Agent{
		cfg:     cfg,
		log:     log,
		exec:    executor.NewClient(cfg.Executor.Socket),
		docker:  docker,
		http:    &http.Client{Transport: &http.Transport{TLSClientConfig: tlsutil.ClientConfig(cert, caPool, u.Hostname())}},
		allowed: allowed,
	}, nil
}

// Run connects to the controller and serves until ctx is done (reconnecting with backoff).
func (a *Agent) Run(ctx context.Context) error {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		conn, resp, err := websocket.Dial(ctx, a.cfg.Controller.URL, &websocket.DialOptions{HTTPClient: a.http})
		if err != nil {
			a.log.Warn("controller dial failed", "err", err)
			if !sleepCtx(ctx, backoff) {
				return ctx.Err()
			}
			backoff = min(backoff*2, 30*time.Second)
			continue
		}
		resp.Body.Close()
		a.log.Info("connected to controller")
		backoff = time.Second
		a.serve(ctx, conn)
		a.log.Info("disconnected from controller")
		if !sleepCtx(ctx, backoff) {
			return ctx.Err()
		}
		backoff = min(backoff*2, 30*time.Second)
	}
}

func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

func (a *Agent) serve(ctx context.Context, conn *websocket.Conn) {
	done := make(chan struct{})
	defer close(done)
	go a.telemetryLoop(ctx, conn, done)
	for {
		rctx, cancel := context.WithTimeout(ctx, 60*time.Second)
		_, data, err := conn.Read(rctx)
		cancel()
		if err != nil {
			return
		}
		var msg protocol.Msg
		if err := json.Unmarshal(data, &msg); err != nil || msg.Type != protocol.MsgRequest {
			continue
		}
		go a.handleRequest(ctx, conn, msg)
	}
}

func (a *Agent) handleRequest(ctx context.Context, conn *websocket.Conn, req protocol.Msg) {
	resp := protocol.Msg{Type: protocol.MsgResponse, ID: req.ID}
	ok := true
	var payload any
	rctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	switch req.Action {
	case protocol.ActionHealth:
		si, err := a.exec.Sysinfo(rctx)
		if err != nil {
			ok = false
			resp.Error = err.Error()
		} else {
			payload = protocol.HealthPayload{Version: Version, Hostname: si.Hostname, UptimeSec: si.UptimeSec}
		}
	case protocol.ActionShutdown:
		if err := a.exec.Poweroff(rctx); err != nil {
			ok = false
			resp.Error = err.Error()
		}
	case protocol.ActionContainersList:
		containers, err := a.listContainers(rctx)
		if err != nil {
			ok = false
			resp.Error = err.Error()
		} else {
			payload = protocol.ContainerListPayload{Containers: containers}
		}
	case protocol.ActionContainerAction:
		var p protocol.ContainerActionPayload
		if err := json.Unmarshal(req.Payload, &p); err != nil {
			ok = false
			resp.Error = "bad payload"
		} else if err := a.doContainerAction(rctx, p); err != nil {
			ok = false
			resp.Error = err.Error()
		}
	default:
		ok = false
		resp.Error = "unknown action"
	}
	resp.OK = &ok
	if ok && payload != nil {
		resp.Payload, _ = json.Marshal(payload)
	}
	b, _ := json.Marshal(resp)
	wctx, cancel2 := context.WithTimeout(ctx, 10*time.Second)
	defer cancel2()
	if err := conn.Write(wctx, websocket.MessageText, b); err != nil {
		a.log.Warn("write response failed", "err", err)
	}
}

func (a *Agent) listContainers(ctx context.Context) ([]protocol.ContainerInfo, error) {
	all, err := a.docker.List(ctx)
	if err != nil {
		return nil, err
	}
	var out []protocol.ContainerInfo
	for _, c := range all {
		for _, name := range c.Names {
			name = strings.TrimPrefix(name, "/")
			if a.allowed[name] {
				out = append(out, protocol.ContainerInfo{Name: name, State: c.State, Status: c.Status})
				break
			}
		}
	}
	return out, nil
}

func (a *Agent) doContainerAction(ctx context.Context, p protocol.ContainerActionPayload) error {
	if !containerNameRe.MatchString(p.Name) {
		return fmt.Errorf("invalid container name")
	}
	if !a.allowed[p.Name] {
		return fmt.Errorf("container %q is not in the whitelist", p.Name)
	}
	switch p.Action {
	case "start", "stop", "restart":
	default:
		return fmt.Errorf("invalid action %q", p.Action)
	}
	return a.docker.Action(ctx, p.Name, p.Action)
}

func (a *Agent) telemetryLoop(ctx context.Context, conn *websocket.Conn, done chan struct{}) {
	ticker := time.NewTicker(a.cfg.Telemetry.Interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-done:
			return
		case <-ticker.C:
		}
		msg := protocol.Msg{Type: protocol.MsgTelemetry, Payload: a.collect(ctx)}
		b, _ := json.Marshal(msg)
		wctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		err := conn.Write(wctx, websocket.MessageText, b)
		cancel()
		if err != nil {
			return
		}
	}
}

func (a *Agent) collect(ctx context.Context) json.RawMessage {
	payload := protocol.TelemetryPayload{Ts: time.Now().UTC().Format(time.RFC3339)}
	rctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		si, err := a.exec.Sysinfo(rctx)
		if err != nil {
			a.log.Debug("sysinfo failed", "err", err)
			return
		}
		payload.Hostname = si.Hostname
		payload.UptimeSec = si.UptimeSec
		payload.CPU = si.Thermals
		payload.RAM = &si.RAM
		payload.Load = &si.Load
	}()
	var gpu protocol.GPUStats
	go func() {
		defer wg.Done()
		d, err := a.exec.Amdsmi(rctx)
		if err != nil {
			a.log.Debug("amdsmi failed", "err", err)
			return
		}
		gpu = ParseAmdsmi(d.Raw)
	}()
	wg.Wait()
	if gpu.Raw != "" {
		payload.GPU = &gpu
	}
	b, _ := json.Marshal(payload)
	return b
}
