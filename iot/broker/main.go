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

// novaAuth: user "nova" (~/anish-ai/.mqtt_key) gets everything (Nova on Mac + hub).
// User "room" (~/anish-ai/.mqtt_room_key, flashed into the room ESP32) gets only home/room/#.
// Anonymous clients (car, phone pages) get only home/car/#. So nobody else on the Wi-Fi (or a web page
// via ws:9001) can switch the room, inject "heard" speech, say/stt/stop jobs, or sleep state.
// Any other username, or "nova" with a wrong password, is refused. (Mochi's Ledger can't express this:
// its empty-username rule matches every name, so "nova"+any password would pass.)
type novaAuth struct {
	mqtt.HookBase
	pw, roomPw []byte
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
	case "room":
		return subtle.ConstantTimeCompare(pk.Connect.Password, h.roomPw) == 1
	}
	return false
}
func (h *novaAuth) OnACLCheck(cl *mqtt.Client, topic string, write bool) bool {
	return allowed(string(cl.Properties.Username), topic) // a username only gets here with its password
}
func allowed(user, t string) bool {
	switch user {
	case "nova":
		return true
	case "room":
		return strings.HasPrefix(t, "home/room/")
	}
	return strings.HasPrefix(t, "home/car/")
}

func main() {
	tcpAddr, wsAddr := ":1883", ":9001"
	if len(os.Args) > 2 { tcpAddr, wsAddr = os.Args[1], os.Args[2] } // test ports
	s := mqtt.New(nil)
	key := func(f string) []byte { // fail closed: no key file -> no broker
		b, err := os.ReadFile(os.Getenv("HOME") + "/anish-ai/" + f)
		if b = bytes.TrimSpace(b); err != nil || len(b) < 16 { log.Fatal("need ~/anish-ai/", f, " (>=16 chars): ", err) }
		return b
	}
	if err := s.AddHook(&novaAuth{pw: key(".mqtt_key"), roomPw: key(".mqtt_room_key")}, nil); err != nil { log.Fatal(err) }
	if err := s.AddListener(listeners.NewTCP(listeners.Config{ID: "tcp", Address: tcpAddr})); err != nil { log.Fatal(err) }
	if err := s.AddListener(listeners.NewWebsocket(listeners.Config{ID: "ws", Address: wsAddr})); err != nil { log.Fatal(err) }
	go func() { if err := s.Serve(); err != nil { log.Fatal(err) } }()
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	s.Close()
}
