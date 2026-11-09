// Nova's MQTT broker for the hub: Mochi (Go). Replaces amqtt, which never closed dead
// client sockets (ESP32 reconnects piled up as CLOSE_WAIT) and leaked ~1 GB/h on the 8 GB hub.
// Same listeners as before: 1883 raw MQTT (devices + Nova), 9001 WebSockets (browser dashboard).
// Build on the M4 for the Intel hub:  GOOS=darwin GOARCH=amd64 go build -o nova-broker .
package main

import (
	"bytes"
	"crypto/subtle"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"

	mqtt "github.com/mochi-mqtt/server/v2"
	"github.com/mochi-mqtt/server/v2/listeners"
	"github.com/mochi-mqtt/server/v2/packets"
)

// novaAuth: user "nova" + the password in ~/anish-ai/.mqtt_key gets everything (Nova on Mac + hub).
// Anonymous clients (ESP32s, phone/dashboard pages) only get home/room/# and home/car/#, so nobody
// else on the Wi-Fi (or a web page via ws:9001) can inject "heard" speech, say/stt/stop jobs, or sleep state.
// Any other username, or "nova" with a wrong password, is refused. (Mochi's Ledger can't express this:
// its empty-username rule matches every name, so "nova"+any password would pass.)
type novaAuth struct {
	mqtt.HookBase
	pw []byte
}

func (h *novaAuth) ID() string { return "nova-auth" }
func (h *novaAuth) Provides(b byte) bool {
	return bytes.Contains([]byte{mqtt.OnConnectAuthenticate, mqtt.OnACLCheck}, []byte{b})
}
func (h *novaAuth) OnConnectAuthenticate(cl *mqtt.Client, pk packets.Packet) bool {
	switch string(cl.Properties.Username) {
	case "":
		return true
	case "nova":
		return subtle.ConstantTimeCompare(pk.Connect.Password, h.pw) == 1
	}
	return false
}
func (h *novaAuth) OnACLCheck(cl *mqtt.Client, topic string, write bool) bool {
	if string(cl.Properties.Username) == "nova" { // only reachable with the right password
		return true
	}
	return deviceTopic(topic)
}
func deviceTopic(t string) bool { return strings.HasPrefix(t, "home/room/") || strings.HasPrefix(t, "home/car/") }

func main() {
	tcpAddr, wsAddr := ":1883", ":9001"
	if len(os.Args) > 2 { tcpAddr, wsAddr = os.Args[1], os.Args[2] } // test ports
	s := mqtt.New(nil)
	pw, err := os.ReadFile(os.Getenv("HOME") + "/anish-ai/.mqtt_key")
	if err != nil || len(bytes.TrimSpace(pw)) < 16 { log.Fatal("need ~/anish-ai/.mqtt_key (>=16 chars): ", err) } // fail closed
	if err := s.AddHook(&novaAuth{pw: bytes.TrimSpace(pw)}, nil); err != nil { log.Fatal(err) }
	if err := s.AddListener(listeners.NewTCP(listeners.Config{ID: "tcp", Address: tcpAddr})); err != nil { log.Fatal(err) }
	if err := s.AddListener(listeners.NewWebsocket(listeners.Config{ID: "ws", Address: wsAddr})); err != nil { log.Fatal(err) }
	go func() { if err := s.Serve(); err != nil { log.Fatal(err) } }()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	s.Close()
}
