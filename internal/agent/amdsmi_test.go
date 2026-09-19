package agent

import "testing"

const sample = `
=================================
AMD Software - Adrenalin Edition 24.10.1
=================================
GPU[0]
GPU use (%)                    :  12
GPU core clock (MHz)           :  1800
GPU memory use (%)             :  34
GPU memory core clock (MHz)    :  1000
GPU temperature (C)            :  47
`

func TestParseAmdsmi(t *testing.T) {
	g := ParseAmdsmi(sample)
	if g.TempC == nil || *g.TempC != 47 {
		t.Errorf("temp = %v", g.TempC)
	}
	if g.UsePct == nil || *g.UsePct != 12 {
		t.Errorf("use = %v", g.UsePct)
	}
	if g.MemUsePct == nil || *g.MemUsePct != 34 {
		t.Errorf("memuse = %v", g.MemUsePct)
	}
	if g.CoreClockMHz == nil || *g.CoreClockMHz != 1800 {
		t.Errorf("core = %v", g.CoreClockMHz)
	}
	if g.MemClockMHz == nil || *g.MemClockMHz != 1000 {
		t.Errorf("memclk = %v", g.MemClockMHz)
	}
	if g.Raw == "" {
		t.Error("raw empty")
	}
}

func TestParseAmdsmiEmpty(t *testing.T) {
	g := ParseAmdsmi("")
	if g.TempC != nil || g.UsePct != nil {
		t.Error("expected nil fields for empty input")
	}
}
