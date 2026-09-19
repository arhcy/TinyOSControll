package dockerapi

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
)

func newMockDocker(t *testing.T) *Client {
	t.Helper()
	ln, err := net.Listen("unix", filepath.Join(t.TempDir(), "docker.sock"))
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/v1.47/containers/json", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`[{"Id":"abc","Names":["/nginx"],"State":"running","Status":"Up 2 hours"}]`))
	})
	mux.HandleFunc("/v1.47/containers/nginx/start", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	srv := httptest.NewUnstartedServer(mux)
	srv.Listener = ln
	go srv.Start()
	t.Cleanup(srv.Close)
	c, err := NewClient("unix://" + ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestDockerListAndAction(t *testing.T) {
	c := newMockDocker(t)
	list, err := c.List(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 || list[0].Names[0] != "/nginx" || list[0].State != "running" {
		t.Errorf("list = %+v", list)
	}
	if err := c.Action(context.Background(), "nginx", "start"); err != nil {
		t.Fatal(err)
	}
	if err := c.Action(context.Background(), "nginx", "bad"); err == nil {
		t.Error("expected error for bad action")
	}
}
