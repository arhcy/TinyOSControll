package wol

import (
	"net"
	"testing"
)

func TestMagicPacket(t *testing.T) {
	mac, _ := net.ParseMAC("AA:BB:CC:DD:EE:FF")
	pkt := MagicPacket(mac)
	if len(pkt) != 102 {
		t.Fatalf("len = %d, want 102", len(pkt))
	}
	for i := 0; i < 6; i++ {
		if pkt[i] != 0xFF {
			t.Fatalf("prefix byte %d = %x", i, pkt[i])
		}
	}
	for i := 0; i < 16; i++ {
		if got := pkt[6+i*6 : 6+i*6+6]; string(got) != string(mac) {
			t.Fatalf("mac copy %d mismatch", i)
		}
	}
}

func TestParseMAC(t *testing.T) {
	for _, valid := range []string{"AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"} {
		if _, err := ParseMAC(valid); err != nil {
			t.Errorf("ParseMAC(%q) error: %v", valid, err)
		}
	}
	for _, invalid := range []string{"", "AA:BB:CC:DD:EE", "GG:BB:CC:DD:EE:FF", "AA-BB-CC-DD-EE-FF", "AA:BB:CC:DD:EE:FF:00"} {
		if _, err := ParseMAC(invalid); err == nil {
			t.Errorf("ParseMAC(%q) should fail", invalid)
		}
	}
}
