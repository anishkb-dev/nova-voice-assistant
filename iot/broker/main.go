// Nova's MQTT broker for the hub: Mochi (Go). Replaces amqtt, which never closed dead
// client sockets (ESP32 reconnects piled up as CLOSE_WAIT) and leaked ~1 GB/h on the 8 GB hub.
// Same listeners as before: 1883 raw MQTT (devices + Nova), 9001 WebSockets (browser dashboard).
// Build on the M4 for the Intel hub:  GOOS=darwin GOARCH=amd64 go build -o nova-broker .
package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	mqtt "github.com/mochi-mqtt/server/v2"
	"github.com/mochi-mqtt/server/v2/hooks/auth"
	"github.com/mochi-mqtt/server/v2/listeners"
)

func main() {
	tcpAddr, wsAddr := ":1883", ":9001"
	if len(os.Args) > 2 { tcpAddr, wsAddr = os.Args[1], os.Args[2] } // test ports
	s := mqtt.New(nil)
	if err := s.AddHook(new(auth.AllowHook), nil); err != nil { log.Fatal(err) } // LAN only, anonymous like before
	if err := s.AddListener(listeners.NewTCP(listeners.Config{ID: "tcp", Address: tcpAddr})); err != nil { log.Fatal(err) }
	if err := s.AddListener(listeners.NewWebsocket(listeners.Config{ID: "ws", Address: wsAddr})); err != nil { log.Fatal(err) }
	go func() { if err := s.Serve(); err != nil { log.Fatal(err) } }()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	s.Close()
}
