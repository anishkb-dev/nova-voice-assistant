package main

import "testing"

func TestDeviceTopic(t *testing.T) {
	for _, ok := range []string{"home/room/ac/set", "home/room/#", "home/car/throttle"} {
		if !deviceTopic(ok) { t.Error("should allow", ok) }
	}
	for _, bad := range []string{"home/hub/heard", "home/mac/stt/1", "home/sleep", "#", "home/+/heard", "home/roomx"} {
		if deviceTopic(bad) { t.Error("should deny", bad) }
	}
}
