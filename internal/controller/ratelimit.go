package controller

import (
	"sync"
	"time"
)

type bucket struct {
	tokens float64
	last   time.Time
}

// RateLimiter is a per-key token bucket.
type RateLimiter struct {
	mu       sync.Mutex
	buckets  map[string]*bucket
	capacity float64
	refill   time.Duration
}

func NewRateLimiter(capacity int, refill time.Duration) *RateLimiter {
	return &RateLimiter{buckets: make(map[string]*bucket), capacity: float64(capacity), refill: refill}
}

func (r *RateLimiter) Allow(key string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	now := time.Now()
	b, ok := r.buckets[key]
	if !ok {
		b = &bucket{tokens: r.capacity, last: now}
		r.buckets[key] = b
	}
	b.tokens += now.Sub(b.last).Seconds() / r.refill.Seconds()
	b.last = now
	if b.tokens > r.capacity {
		b.tokens = r.capacity
	}
	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}
