import QtQuick

// Game clock moving between game answers: time of last answer moved on at its rate for the seconds since
// that answer (capped), "h:mm:ss" with format(). A Timer: ticks only while active & the clock moves.
// Bind time, received & rate to values read once per game answer (not to backend: one Python read per tick)
Timer {
    id: clock
    property real time: 0  // seconds, last game answer
    property real received: 0  // Date.now() of last game answer (ms)
    property real rate: 1  // clock seconds per second (replay speed, 0: still)
    property real maxGap: 3  // seconds moved on at most without a game answer
    property bool active: true  // clock shown & page shown
    property real now: time  // shown time

    function format(seconds) {
        var total = Math.max(Math.floor(seconds), 0)
        var hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60, rest = total % 60
        return hours + ":" + (minutes < 10 ? "0" : "") + minutes + ":" + (rest < 10 ? "0" : "") + rest
    }
    // Game answer: shown time back to answered time
    function sync() { now = time }
    onTimeChanged: sync()
    onReceivedChanged: sync()
    onRateChanged: sync()

    interval: 250
    repeat: true
    running: active && rate !== 0
    onTriggered: now = time + rate * Math.min(Math.max((Date.now() - received) / 1000, 0), maxGap)
}
