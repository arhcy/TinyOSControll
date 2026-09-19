//go:build linux

package wol

import (
	"net"

	"golang.org/x/sys/unix"
)

// setBroadcast enables SO_BROADCAST on the UDP socket (required on Linux).
func setBroadcast(c net.PacketConn) error {
	uc, ok := c.(*net.UDPConn)
	if !ok {
		return nil
	}
	sc, err := uc.SyscallConn()
	if err != nil {
		return err
	}
	var setErr error
	_ = sc.Control(func(fd uintptr) {
		setErr = unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_BROADCAST, 1)
	})
	return setErr
}
