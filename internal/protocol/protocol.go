// Package protocol defines the wire messages exchanged between controller and agent.
package protocol

import "encoding/json"

// Message types.
const (
	MsgRequest   = "request"
	MsgResponse  = "response"
	MsgTelemetry = "telemetry"
)

// Management actions.
const (
	ActionHealth          = "health"
	ActionShutdown        = "shutdown"
	ActionContainersList  = "containers.list"
	ActionContainerAction = "containers.action"
)

// Msg is a single WebSocket frame payload.
type Msg struct {
	Type    string          `json:"type"`
	ID      string          `json:"id,omitempty"`
	Action  string          `json:"action,omitempty"`
	OK      *bool           `json:"ok,omitempty"`
	Error   string          `json:"error,omitempty"`
	Payload json.RawMessage `json:"payload,omitempty"`
}

// --- Management payloads ---

// HealthPayload is returned by the "health" action.
type HealthPayload struct {
	Version   string  `json:"version"`
	Hostname  string  `json:"hostname"`
	UptimeSec float64 `json:"uptime_sec"`
}

// ContainerInfo describes one managed container.
type ContainerInfo struct {
	Name   string `json:"name"`
	State  string `json:"state"`
	Status string `json:"status"`
}

// ContainerListPayload is returned by "containers.list".
type ContainerListPayload struct {
	Containers []ContainerInfo `json:"containers"`
}

// ContainerActionPayload is sent with "containers.action".
type ContainerActionPayload struct {
	Name   string `json:"name"`
	Action string `json:"action"` // start | stop | restart
}

// --- Telemetry payloads ---

// ThermalZone is one CPU/GPU thermal zone.
type ThermalZone struct {
	Type  string  `json:"type"`
	TempC float64 `json:"temp_c"`
}

// RAMStats is host memory usage.
type RAMStats struct {
	TotalKB     uint64  `json:"total_kb"`
	AvailableKB uint64  `json:"available_kb"`
	UsedKB      uint64  `json:"used_kb"`
	UsedPct     float64 `json:"used_pct"`
}

// LoadStats is host load average.
type LoadStats struct {
	L1  float64 `json:"l1"`
	L5  float64 `json:"l5"`
	L15 float64 `json:"l15"`
}

// GPUStats is parsed amd-smi monitor data (nil fields = not present in output).
type GPUStats struct {
	Raw          string   `json:"raw"`
	TempC        *float64 `json:"temp_c,omitempty"`
	UsePct       *float64 `json:"use_pct,omitempty"`
	MemUsePct    *float64 `json:"mem_use_pct,omitempty"`
	CoreClockMHz *int     `json:"core_clock_mhz,omitempty"`
	MemClockMHz  *int     `json:"mem_clock_mhz,omitempty"`
}

// TelemetryPayload is one telemetry frame (agent -> controller).
type TelemetryPayload struct {
	Ts        string        `json:"ts"`
	Hostname  string        `json:"hostname"`
	UptimeSec float64       `json:"uptime_sec"`
	CPU       []ThermalZone `json:"cpu"`
	RAM       *RAMStats     `json:"ram,omitempty"`
	Load      *LoadStats    `json:"load,omitempty"`
	GPU       *GPUStats     `json:"gpu,omitempty"`
}
