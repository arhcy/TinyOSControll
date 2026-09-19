// Package tlsutil loads certificates and builds mTLS configurations.
package tlsutil

import (
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"
)

// LoadCA reads a PEM CA certificate into a cert pool.
func LoadCA(path string) (*x509.CertPool, error) {
	pem, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read CA %s: %w", path, err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(pem) {
		return nil, fmt.Errorf("no valid CA certificate in %s", path)
	}
	return pool, nil
}

// LoadCert reads a PEM certificate and key pair.
func LoadCert(certPath, keyPath string) (tls.Certificate, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return tls.Certificate{}, fmt.Errorf("load cert %s/%s: %w", certPath, keyPath, err)
	}
	return cert, nil
}

// ServerConfig builds a TLS config for an mTLS server (requires client certs).
func ServerConfig(cert tls.Certificate, caPool *x509.CertPool) *tls.Config {
	return &tls.Config{
		MinVersion:   tls.VersionTLS12,
		Certificates: []tls.Certificate{cert},
		ClientCAs:    caPool,
		ClientAuth:   tls.RequireAndVerifyClientCert,
	}
}

// ClientConfig builds a TLS config for an mTLS client.
func ClientConfig(cert tls.Certificate, caPool *x509.CertPool, serverName string) *tls.Config {
	return &tls.Config{
		MinVersion:   tls.VersionTLS12,
		Certificates: []tls.Certificate{cert},
		RootCAs:      caPool,
		ServerName:   serverName,
	}
}
