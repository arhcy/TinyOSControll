package executor

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"time"
)

// Client talks to the host executor over a unix socket (JSON lines).
type Client struct {
	SocketPath string
}

func NewClient(socketPath string) *Client { return &Client{SocketPath: socketPath} }

func (c *Client) call(ctx context.Context, cmd string) (*Response, error) {
	d := net.Dialer{Timeout: 3 * time.Second}
	conn, err := d.DialContext(ctx, "unix", c.SocketPath)
	if err != nil {
		return nil, fmt.Errorf("dial executor: %w", err)
	}
	defer conn.Close()
	deadline, _ := ctx.Deadline()
	if deadline.IsZero() {
		deadline = time.Now().Add(20 * time.Second)
	}
	conn.SetDeadline(deadline)
	req, _ := json.Marshal(Request{Cmd: cmd})
	if _, err := conn.Write(append(req, '\n')); err != nil {
		return nil, err
	}
	line, err := bufio.NewReader(conn).ReadBytes('\n')
	if err != nil {
		return nil, err
	}
	var resp Response
	if err := json.Unmarshal(line, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Sysinfo(ctx context.Context) (*SysinfoData, error) {
	resp, err := c.call(ctx, CmdSysinfo)
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, fmt.Errorf("executor: %s", resp.Error)
	}
	var d SysinfoData
	if err := json.Unmarshal(resp.Data, &d); err != nil {
		return nil, err
	}
	return &d, nil
}

func (c *Client) Amdsmi(ctx context.Context) (*AmdsmiData, error) {
	resp, err := c.call(ctx, CmdAmdsmi)
	if err != nil {
		return nil, err
	}
	if !resp.OK {
		return nil, fmt.Errorf("executor: %s", resp.Error)
	}
	var d AmdsmiData
	if err := json.Unmarshal(resp.Data, &d); err != nil {
		return nil, err
	}
	return &d, nil
}

func (c *Client) Poweroff(ctx context.Context) error {
	resp, err := c.call(ctx, CmdPoweroff)
	if err != nil {
		return err
	}
	if !resp.OK {
		return fmt.Errorf("executor: %s", resp.Error)
	}
	return nil
}
