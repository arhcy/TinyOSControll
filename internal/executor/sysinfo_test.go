package executor

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSysinfoCollect(t *testing.T) {
	tmp := t.TempDir()
	thermal := filepath.Join(tmp, "thermal")
	proc := filepath.Join(tmp, "proc")
	if err := os.MkdirAll(filepath.Join(thermal, "thermal_zone0"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(proc, 0o755); err != nil {
		t.Fatal(err)
	}
	os.WriteFile(filepath.Join(thermal, "thermal_zone0", "temp"), []byte("45500\n"), 0o644)
	os.WriteFile(filepath.Join(thermal, "thermal_zone0", "type"), []byte("x86_pkg_temp\n"), 0o644)
	os.WriteFile(filepath.Join(proc, "meminfo"), []byte("MemTotal:       16384000 kB\nMemAvailable:   8192000 kB\n"), 0o644)
	os.WriteFile(filepath.Join(proc, "loadavg"), []byte("0.50 0.40 0.30 1/200 123\n"), 0o644)
	os.WriteFile(filepath.Join(proc, "uptime"), []byte("12345.6 23456.7\n"), 0o644)

	s := &SysinfoSource{ThermalRoot: thermal, ProcRoot: proc}
	d, err := s.Collect()
	if err != nil {
		t.Fatal(err)
	}
	if len(d.Thermals) != 1 || d.Thermals[0].TempC != 45.5 || d.Thermals[0].Type != "x86_pkg_temp" {
		t.Errorf("thermals = %+v", d.Thermals)
	}
	if d.RAM.TotalKB != 16384000 || d.RAM.AvailableKB != 8192000 || d.RAM.UsedKB != 8192000 {
		t.Errorf("ram = %+v", d.RAM)
	}
	if d.RAM.UsedPct != 50 {
		t.Errorf("ram pct = %v", d.RAM.UsedPct)
	}
	if d.Load.L1 != 0.5 || d.Load.L15 != 0.3 || d.UptimeSec != 12345.6 {
		t.Errorf("load/uptime = %+v / %v", d.Load, d.UptimeSec)
	}
}
