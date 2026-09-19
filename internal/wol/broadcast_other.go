//go:build !linux

package wol

import "net"

// setBroadcast is a no-op on platforms without SO_BROADCAST.
func setBroadcast(c net.PacketConn) error { return nil }
