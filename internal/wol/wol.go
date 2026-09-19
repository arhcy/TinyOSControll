// Package wol builds and sends Wake-on-LAN magic packets.
package wol

import (
	"context"
	"fmt"
	"net"
	"regexp"
	"strings"
	"time"
)

var macRe = regexp.MustCompile(`^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$`)

// ParseMAC validates and parses a MAC address string.
func ParseMAC(s string) (net.HardwareAddr, error) {
	s = strings.TrimSpace(s)
	if !macRe.MatchString(s) {
		return nil, fmt.Errorf("invalid MAC address %q", s)
	}
	mac, err := net.ParseMAC(s)
	if err != nil {
		return nil, err
	}
	return mac, nil
}

// MagicPacket builds the 102-byte WoL magic packet: 6x 0xFF + 16x MAC.
func MagicPacket(mac net.HardwareAddr) []byte {
	pkt := make([]byte, 102)
	for i := 0; i < 6; i++ {
		pkt[i] = 0xFF
	}
	for i := 0; i < 16; i++ {
		copy(pkt[6+i*6:], mac)
	}
	return pkt
}

// Sender sends magic packets over UDP.
type Sender struct {
	Port int
	// Dial is overridable for tests.
	Dial func(network string, laddr *net.UDPAddr) (net.PacketConn, error)
}

// Send broadcasts the magic packet to 255.255.255.255 and, if directedIP is
// set, also sends it to that IP.
func (s *Sender) Send(ctx context.Context, mac net.HardwareAddr, directedIP string) error {
	if s.Port <= 0 {
		s.Port = 9
	}
	dial := s.Dial
	if dial == nil {
		dial = func(network string, laddr *net.UDPAddr) (net.PacketConn, error) {
			return net.ListenPacket(network, laddr.String())
		}
	}
	conn, err := dial("udp4", &net.UDPAddr{IP: net.IPv4(0, 0, 0, 0)})
	if err != nil {
		return fmt.Errorf("open udp: %w", err)
	}
	defer conn.Close()
	if err := setBroadcast(conn); err != nil {
		return fmt.Errorf("set broadcast: %w", err)
	}
	if deadline, ok := ctx.Deadline(); ok {
		conn.SetDeadline(deadline)
	} else {
		conn.SetDeadline(time.Now().Add(5 * time.Second))
	}
	pkt := MagicPacket(mac)
	if _, err := conn.WriteTo(pkt, &net.UDPAddr{IP: net.IPv4bcast, Port: s.Port}); err != nil {
		return fmt.Errorf("broadcast: %w", err)
	}
	if directedIP != "" {
		ip := net.ParseIP(directedIP)
		if ip == nil {
			return fmt.Errorf("invalid directed IP %q", directedIP)
		}
		if _, err := conn.WriteTo(pkt, &net.UDPAddr{IP: ip, Port: s.Port}); err != nil {
			return fmt.Errorf("directed: %w", err)
		}
	}
	return nil
}
