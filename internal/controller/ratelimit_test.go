package controller

import (
	"testing"
	"time"
)

func TestRateLimiter(t *testing.T) {
	r := NewRateLimiter(3, time.Second)
	for i := 0; i < 3; i++ {
		if !r.Allow("ip") {
			t.Fatalf("allow %d failed", i)
		}
	}
	if r.Allow("ip") {
		t.Error("4th request should be limited")
	}
	if !r.Allow("other") {
		t.Error("other key should be allowed")
	}
}

func TestHubPublish(t *testing.T) {
	h := NewHub()
	ch, cancel := h.Subscribe()
	defer cancel()
	h.Publish("telemetry", []byte(`{"x":1}`))
	select {
	case ev := <-ch:
		if ev.event != "telemetry" || string(ev.data) != `{"x":1}` {
			t.Errorf("ev = %+v", ev)
		}
	default:
		t.Fatal("no event received")
	}
}
