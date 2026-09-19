// Package dockerapi is a minimal Docker Engine API client (list + container actions).
package dockerapi

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"strings"
	"time"
)

const apiVersion = "v1.47"

// Container is a subset of the Docker container listing entry.
type Container struct {
	ID     string   `json:"Id"`
	Names  []string `json:"Names"`
	State  string   `json:"State"`
	Status string   `json:"Status"`
}

// Client talks to the Docker API (via docker-socket-proxy) over unix socket or tcp.
type Client struct {
	base       string
	httpClient *http.Client
}

func NewClient(endpoint string) (*Client, error) {
	switch {
	case strings.HasPrefix(endpoint, "unix://"):
		path := strings.TrimPrefix(endpoint, "unix://")
		transport := &http.Transport{
			DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
				var d net.Dialer
				return d.DialContext(ctx, "unix", path)
			},
		}
		return &Client{base: "http://docker/" + apiVersion, httpClient: &http.Client{Transport: transport, Timeout: 10 * time.Second}}, nil
	case strings.HasPrefix(endpoint, "tcp://"):
		host := strings.TrimPrefix(endpoint, "tcp://")
		return &Client{base: "http://" + host + "/" + apiVersion, httpClient: &http.Client{Timeout: 10 * time.Second}}, nil
	default:
		return nil, fmt.Errorf("unsupported docker endpoint %q (want unix:// or tcp://)", endpoint)
	}
}

// List returns all containers.
func (c *Client) List(ctx context.Context) ([]Container, error) {
	var out []Container
	if err := c.do(ctx, http.MethodGet, "/containers/json", &out); err != nil {
		return nil, err
	}
	return out, nil
}

// Action starts, stops or restarts a container by name.
func (c *Client) Action(ctx context.Context, name, action string) error {
	switch action {
	case "start", "stop", "restart":
	default:
		return fmt.Errorf("invalid action %q", action)
	}
	return c.do(ctx, http.MethodPost, "/containers/"+name+"/"+action, nil)
}

func (c *Client) do(ctx context.Context, method, path string, out any) error {
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, nil)
	if err != nil {
		return err
	}
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	switch resp.StatusCode {
	case http.StatusOK, http.StatusNoContent, http.StatusNotModified:
		// 304: already in the desired state
	case http.StatusConflict:
		return fmt.Errorf("container already in desired state")
	case http.StatusNotFound:
		return fmt.Errorf("container not found")
	default:
		return fmt.Errorf("docker api: status %d", resp.StatusCode)
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}
