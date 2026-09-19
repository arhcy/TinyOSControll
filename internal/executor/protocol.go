package executor

import (
	"encoding/json"

	"osagent/internal/protocol"
)

// Executor command names (fixed allowlist, no arbitrary commands).
const (
	CmdSysinfo  = "sysinfo"
	CmdAmdsmi   = "amdsmi"
	CmdPoweroff = "poweroff"
)

// Request is one JSON line sent to the executor socket.
type Request struct {
	Cmd string `json:"cmd"`
}

// Response is one JSON line returned by the executor.
type Response struct {
	OK    bool            `json:"ok"`
	Error string          `json:"error,omitempty"`
	Data  json.RawMessage `json:"data,omitempty"`
}

// SysinfoData is host telemetry (no sudo required on the host).
type SysinfoData struct {
	Thermals  []protocol.ThermalZone `json:"thermals"`
	RAM       protocol.RAMStats      `json:"ram"`
	Load      protocol.LoadStats     `json:"load"`
	UptimeSec float64                `json:"uptime_sec"`
	Hostname  string                 `json:"hostname"`
}

// AmdsmiData carries raw amd-smi monitor output.
type AmdsmiData struct {
	Raw string `json:"raw"`
}
