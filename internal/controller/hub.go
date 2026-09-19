package controller

import "sync"

type sseEvent struct {
	event string
	data  []byte
}

// Hub fans events out to SSE subscribers.
type Hub struct {
	mu   sync.Mutex
	subs map[chan sseEvent]struct{}
}

func NewHub() *Hub {
	return &Hub{subs: make(map[chan sseEvent]struct{})}
}

func (h *Hub) Subscribe() (chan sseEvent, func()) {
	h.mu.Lock()
	ch := make(chan sseEvent, 64)
	h.subs[ch] = struct{}{}
	h.mu.Unlock()
	return ch, func() {
		h.mu.Lock()
		if _, ok := h.subs[ch]; ok {
			delete(h.subs, ch)
			close(ch)
		}
		h.mu.Unlock()
	}
}

// Publish delivers an event to all subscribers (drops for slow ones).
func (h *Hub) Publish(event string, data []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for ch := range h.subs {
		select {
		case ch <- sseEvent{event: event, data: data}:
		default:
		}
	}
}
