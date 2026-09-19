package controller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math/rand"
	"sync"
	"sync/atomic"
	"time"

	"nhooyr.io/websocket"

	"osagent/internal/protocol"
	"osagent/internal/telemetry"
)

// AgentClient manages the single mTLS WebSocket connection from the agent.
type AgentClient struct {
	log      *slog.Logger
	hub      *Hub
	store    *telemetry.Store
	online   atomic.Bool
	incoming chan *websocket.Conn

	mu      sync.Mutex
	conn    *websocket.Conn
	pending map[string]chan protocol.Msg
}

func NewAgentClient(log *slog.Logger, hub *Hub, store *telemetry.Store) *AgentClient {
	return &AgentClient{
		log:      log,
		hub:      hub,
		store:    store,
		incoming: make(chan *websocket.Conn, 1),
		pending:  make(map[string]chan protocol.Msg),
	}
}

// Accept hands an accepted connection to the client.
func (a *AgentClient) Accept(conn *websocket.Conn) {
	select {
	case a.incoming <- conn:
	default:
		_ = conn.Close(websocket.StatusNormalClosure, "busy")
	}
}

func (a *AgentClient) Online() bool { return a.online.Load() }

// Run blocks until ctx is done.
func (a *AgentClient) Run(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case conn := <-a.incoming:
			a.serveConnection(ctx, conn)
		}
	}
}

func (a *AgentClient) serveConnection(ctx context.Context, conn *websocket.Conn) {
	a.mu.Lock()
	old := a.conn
	a.conn = conn
	a.mu.Unlock()
	if old != nil {
		_ = old.Close(websocket.StatusNormalClosure, "replaced")
	}
	a.online.Store(true)
	a.log.Info("agent connected")
	done := make(chan struct{})
	go a.reader(conn, done)
	select {
	case <-done:
	case <-ctx.Done():
		_ = conn.Close(websocket.StatusGoingAway, "shutdown")
		<-done
	}
	a.mu.Lock()
	if a.conn == conn {
		a.conn = nil
	}
	a.mu.Unlock()
	a.online.Store(false)
	a.log.Info("agent disconnected")
}

func (a *AgentClient) reader(conn *websocket.Conn, done chan struct{}) {
	defer close(done)
	for {
		rctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		_, data, err := conn.Read(rctx)
		cancel()
		if err != nil {
			return
		}
		a.handleMessage(data)
	}
}

func (a *AgentClient) handleMessage(data []byte) {
	var msg protocol.Msg
	if err := json.Unmarshal(data, &msg); err != nil {
		return
	}
	switch msg.Type {
	case protocol.MsgResponse:
		a.mu.Lock()
		ch, ok := a.pending[msg.ID]
		a.mu.Unlock()
		if ok {
			ch <- msg
		}
	case protocol.MsgTelemetry:
		var f protocol.TelemetryPayload
		if err := json.Unmarshal(msg.Payload, &f); err != nil {
			return
		}
		a.store.Add(f)
		a.hub.Publish("telemetry", data)
	}
}

// Request sends a management request and waits for the matching response.
func (a *AgentClient) Request(ctx context.Context, action string, payload any) (json.RawMessage, error) {
	a.mu.Lock()
	conn := a.conn
	a.mu.Unlock()
	if conn == nil {
		return nil, errors.New("agent offline")
	}
	id := fmt.Sprintf("%x", rand.Int63())
	ch := make(chan protocol.Msg, 1)
	a.mu.Lock()
	a.pending[id] = ch
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		delete(a.pending, id)
		a.mu.Unlock()
	}()
	var p json.RawMessage
	if payload != nil {
		p, _ = json.Marshal(payload)
	}
	b, _ := json.Marshal(protocol.Msg{Type: protocol.MsgRequest, ID: id, Action: action, Payload: p})
	wctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	if err := conn.Write(wctx, websocket.MessageText, b); err != nil {
		return nil, err
	}
	select {
	case m := <-ch:
		if m.OK != nil && !*m.OK {
			return nil, errors.New(m.Error)
		}
		return m.Payload, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}
