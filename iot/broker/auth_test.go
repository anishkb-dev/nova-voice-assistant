package main

import "testing"

func TestAllowed(t *testing.T) {
	cases := []struct {
		user, topic string
		ok          bool
	}{
		{"nova", "home/hub/heard", true}, {"nova", "#", true},
		{"room", "home/room/ac/set", true}, {"room", "home/room/#", true},
		{"room", "home/hub/heard", false}, {"room", "home/car/throttle", false}, {"room", "#", false},
		{"", "home/car/throttle", true}, {"", "home/room/light/set", false}, {"", "home/hub/heard", false},
		{"", "home/sleep", false}, {"", "#", false}, {"", "home/+/heard", false},
	}
	for _, c := range cases {
		if allowed(c.user, c.topic) != c.ok { t.Errorf("%q %q want %v", c.user, c.topic, c.ok) }
	}
}
