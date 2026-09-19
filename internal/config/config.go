// Package config loads and validates controller and agent configuration.
package config

import (
	"errors"
	"fmt"
	"net"
	"os"
	"regexp"
	"time"

	"gopkg.in/yaml.v3"
)

var macRe = regexp.MustCompile(`^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$`)

// ControllerConfig is the controller (web panel host) configuration.
type ControllerConfig struct {
	Listen struct {
		Web        string `yaml:"web"`
		Management string `yaml:"management"`
	} `yaml:"listen"`
	APIToken string `yaml:"api_token"`
	WoL      struct {
		MAC  string `yaml:"mac"`
		IP   string `yaml:"ip"`
		Port int    `yaml:"port"`
	} `yaml:"wol"`
	Telemetry struct {
		HistoryMinutes int `yaml:"history_minutes"`
	} `yaml:"telemetry"`
	TLS struct {
		CA   string `yaml:"ca"`
		Cert string `yaml:"cert"`
		Key  string `yaml:"key"`
	} `yaml:"tls"`
	LogLevel string `yaml:"log_level"`
}

// AgentConfig is the target-host agent configuration.
type AgentConfig struct {
	Controller struct {
		URL string `yaml:"url"`
	} `yaml:"controller"`
	Executor struct {
		Socket string `yaml:"socket"`
	} `yaml:"executor"`
	Docker struct {
		Endpoint   string   `yaml:"endpoint"`
		Containers []string `yaml:"containers"`
	} `yaml:"docker"`
	Telemetry struct {
		Interval time.Duration `yaml:"interval"`
	} `yaml:"telemetry"`
	TLS struct {
		CA   string `yaml:"ca"`
		Cert string `yaml:"cert"`
		Key  string `yaml:"key"`
	} `yaml:"tls"`
	LogLevel string `yaml:"log_level"`
}

// LoadController reads and validates the controller config file.
func LoadController(path string) (*ControllerConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}
	var c ControllerConfig
	if err := yaml.Unmarshal(data, &c); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	if err := c.Validate(); err != nil {
		return nil, err
	}
	return &c, nil
}

// Validate checks controller configuration invariants.
func (c *ControllerConfig) Validate() error {
	var errs []error
	if c.Listen.Web == "" {
		errs = append(errs, errors.New("listen.web is required"))
	}
	if c.Listen.Management == "" {
		errs = append(errs, errors.New("listen.management is required"))
	}
	if len(c.APIToken) < 16 {
		errs = append(errs, errors.New("api_token must be at least 16 characters"))
	}
	if !macRe.MatchString(c.WoL.MAC) {
		errs = append(errs, fmt.Errorf("wol.mac %q is not a valid MAC address", c.WoL.MAC))
	}
	if c.WoL.IP != "" && net.ParseIP(c.WoL.IP) == nil {
		errs = append(errs, fmt.Errorf("wol.ip %q is not a valid IP", c.WoL.IP))
	}
	if c.WoL.Port <= 0 || c.WoL.Port > 65535 {
		c.WoL.Port = 9
	}
	if c.Telemetry.HistoryMinutes <= 0 {
		c.Telemetry.HistoryMinutes = 60
	}
	for name, p := range map[string]string{"tls.ca": c.TLS.CA, "tls.cert": c.TLS.Cert, "tls.key": c.TLS.Key} {
		if p == "" {
			errs = append(errs, errors.New(name+" is required"))
		}
	}
	return errors.Join(errs...)
}

// LoadAgent reads and validates the agent config file.
func LoadAgent(path string) (*AgentConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}
	var a AgentConfig
	if err := yaml.Unmarshal(data, &a); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}
	if err := a.Validate(); err != nil {
		return nil, err
	}
	return &a, nil
}

// Validate checks agent configuration invariants.
func (a *AgentConfig) Validate() error {
	var errs []error
	if !isWSS(a.Controller.URL) {
		errs = append(errs, errors.New(`controller.url must be a wss:// URL`))
	}
	if a.Executor.Socket == "" {
		errs = append(errs, errors.New("executor.socket is required"))
	}
	if a.Docker.Endpoint == "" {
		errs = append(errs, errors.New("docker.endpoint is required"))
	}
	if len(a.Docker.Containers) == 0 {
		errs = append(errs, errors.New("docker.containers whitelist must not be empty"))
	}
	for _, n := range a.Docker.Containers {
		if !containerNameRe.MatchString(n) {
			errs = append(errs, fmt.Errorf("docker.containers: invalid name %q", n))
		}
	}
	if a.Telemetry.Interval < time.Second {
		a.Telemetry.Interval = time.Second
	}
	for name, p := range map[string]string{"tls.ca": a.TLS.CA, "tls.cert": a.TLS.Cert, "tls.key": a.TLS.Key} {
		if p == "" {
			errs = append(errs, errors.New(name+" is required"))
		}
	}
	return errors.Join(errs...)
}

var containerNameRe = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)

func isWSS(u string) bool {
	if len(u) < 6 || u[:6] != "wss://" {
		return false
	}
	host := u[6:]
	if i := indexByte(host, '/'); i >= 0 {
		host = host[:i]
	}
	return host != ""
}

func indexByte(s string, b byte) int {
	for i := 0; i < len(s); i++ {
		if s[i] == b {
			return i
		}
	}
	return -1
}
