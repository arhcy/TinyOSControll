package executor

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"osagent/internal/protocol"
)

// SysinfoSource reads host telemetry from sysfs/proc. Roots are injectable for tests.
type SysinfoSource struct {
	ThermalRoot string
	ProcRoot    string
}

func DefaultSysinfoSource() *SysinfoSource {
	return &SysinfoSource{ThermalRoot: "/sys/class/thermal", ProcRoot: "/proc"}
}

func (s *SysinfoSource) Collect() (*SysinfoData, error) {
	d := &SysinfoData{Hostname: hostname()}

	entries, err := os.ReadDir(s.ThermalRoot)
	if err == nil {
		for _, e := range entries {
			if !e.IsDir() || !strings.HasPrefix(e.Name(), "thermal_zone") {
				continue
			}
			base := filepath.Join(s.ThermalRoot, e.Name())
			tempRaw, err := os.ReadFile(filepath.Join(base, "temp"))
			if err != nil {
				continue
			}
			milli, err := strconv.ParseInt(strings.TrimSpace(string(tempRaw)), 10, 64)
			if err != nil {
				continue
			}
			zone := protocol.ThermalZone{TempC: float64(milli) / 1000.0}
			if t, err := os.ReadFile(filepath.Join(base, "type")); err == nil {
				zone.Type = strings.TrimSpace(string(t))
			}
			d.Thermals = append(d.Thermals, zone)
		}
	}

	if total, avail, ok := readMeminfo(filepath.Join(s.ProcRoot, "meminfo")); ok {
		used := total
		if total > avail {
			used = total - avail
		}
		pct := 0.0
		if total > 0 {
			pct = float64(used) / float64(total) * 100
		}
		d.RAM = protocol.RAMStats{TotalKB: total, AvailableKB: avail, UsedKB: used, UsedPct: pct}
	}

	if f, err := os.ReadFile(filepath.Join(s.ProcRoot, "loadavg")); err == nil {
		var l1, l5, l15 float64
		fmt.Sscanf(string(f), "%f %f %f", &l1, &l5, &l15)
		d.Load = protocol.LoadStats{L1: l1, L5: l5, L15: l15}
	}
	if f, err := os.ReadFile(filepath.Join(s.ProcRoot, "uptime")); err == nil {
		fmt.Sscanf(string(f), "%f", &d.UptimeSec)
	}
	return d, nil
}

func readMeminfo(path string) (total, avail uint64, ok bool) {
	f, err := os.ReadFile(path)
	if err != nil {
		return 0, 0, false
	}
	for _, line := range strings.Split(string(f), "\n") {
		switch {
		case strings.HasPrefix(line, "MemTotal:"):
			total = parseMemKB(line)
		case strings.HasPrefix(line, "MemAvailable:"):
			avail = parseMemKB(line)
		}
	}
	return total, avail, total > 0
}

func parseMemKB(line string) uint64 {
	fields := strings.Fields(line)
	if len(fields) < 2 {
		return 0
	}
	v, _ := strconv.ParseUint(fields[1], 10, 64)
	return v
}

func hostname() string {
	h, err := os.Hostname()
	if err != nil {
		return "unknown"
	}
	return h
}
