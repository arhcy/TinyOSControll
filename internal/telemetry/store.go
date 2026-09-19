package telemetry

import (
	"sync"

	"osagent/internal/protocol"
)

// Store keeps recent telemetry frames in a ring buffer.
type Store struct {
	mu      sync.RWMutex
	frames  []protocol.TelemetryPayload
	max     int
	last    protocol.TelemetryPayload
	hasLast bool
}

func NewStore(max int) *Store {
	if max <= 0 {
		max = 3600
	}
	return &Store{max: max}
}

func (s *Store) Add(f protocol.TelemetryPayload) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.last = f
	s.hasLast = true
	s.frames = append(s.frames, f)
	if len(s.frames) > s.max {
		s.frames = s.frames[len(s.frames)-s.max:]
	}
}

func (s *Store) Latest() (protocol.TelemetryPayload, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.last, s.hasLast
}

func (s *Store) History() []protocol.TelemetryPayload {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]protocol.TelemetryPayload, len(s.frames))
	copy(out, s.frames)
	return out
}
