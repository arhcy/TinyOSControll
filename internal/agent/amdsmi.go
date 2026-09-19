package agent

import (
	"regexp"
	"strconv"
	"strings"

	"osagent/internal/protocol"
)

var (
	reGPUTemp   = regexp.MustCompile(`(?m)GPU temperature \(C\)\s*:\s*([\d.]+)`)
	reGPUUse    = regexp.MustCompile(`(?m)GPU use \(\%\)\s*:\s*([\d.]+)`)
	reGPUMemUse = regexp.MustCompile(`(?m)GPU memory use \(\%\)\s*:\s*([\d.]+)`)
	reCoreClock = regexp.MustCompile(`(?m)GPU core clock \(MHz\)\s*:\s*([\d.]+)`)
	reMemClock  = regexp.MustCompile(`(?m)GPU memory core clock \(MHz\)\s*:\s*([\d.]+)`)
)

// ParseAmdsmi extracts GPU metrics from amd-smi monitor output (first GPU).
func ParseAmdsmi(raw string) protocol.GPUStats {
	g := protocol.GPUStats{Raw: strings.TrimSpace(raw)}
	if m := reGPUTemp.FindStringSubmatch(raw); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			g.TempC = &v
		}
	}
	if m := reGPUUse.FindStringSubmatch(raw); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			g.UsePct = &v
		}
	}
	if m := reGPUMemUse.FindStringSubmatch(raw); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			g.MemUsePct = &v
		}
	}
	if m := reCoreClock.FindStringSubmatch(raw); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			vi := int(v)
			g.CoreClockMHz = &vi
		}
	}
	if m := reMemClock.FindStringSubmatch(raw); m != nil {
		if v, err := strconv.ParseFloat(m[1], 64); err == nil {
			vi := int(v)
			g.MemClockMHz = &vi
		}
	}
	return g
}
