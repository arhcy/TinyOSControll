package config

import "testing"

func TestControllerValidate(t *testing.T) {
	c := &ControllerConfig{}
	c.Listen.Web = ":8443"
	c.Listen.Management = ":9443"
	c.APIToken = "0123456789abcdef"
	c.WoL.MAC = "AA:BB:CC:DD:EE:FF"
	c.TLS.CA = "/x/ca.crt"
	c.TLS.Cert = "/x/c.crt"
	c.TLS.Key = "/x/c.key"
	if err := c.Validate(); err != nil {
		t.Fatalf("valid config rejected: %v", err)
	}
	c.WoL.MAC = "bad"
	if err := c.Validate(); err == nil {
		t.Error("bad MAC accepted")
	}
}

func TestAgentValidate(t *testing.T) {
	a := &AgentConfig{}
	a.Controller.URL = "wss://192.168.1.20:9443"
	a.Executor.Socket = "/run/osagent/executor.sock"
	a.Docker.Endpoint = "unix:///x/docker.sock"
	a.Docker.Containers = []string{"nginx"}
	a.TLS.CA = "/x/ca.crt"
	a.TLS.Cert = "/x/a.crt"
	a.TLS.Key = "/x/a.key"
	if err := a.Validate(); err != nil {
		t.Fatalf("valid config rejected: %v", err)
	}
	a.Controller.URL = "http://x"
	if err := a.Validate(); err == nil {
		t.Error("non-wss url accepted")
	}
	a.Docker.Containers = []string{"bad name!"}
	if err := a.Validate(); err == nil {
		t.Error("bad container name accepted")
	}
}
