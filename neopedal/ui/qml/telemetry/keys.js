.pragma library
// Key helpers shared by QML pages (charts & track map of lap viewer)

// Digit of key (0-9, else -1), also digit row of layouts typing other characters there without Shift
// (French AZERTY: & é " ' ( - è _ ç à): Windows scan codes of digit row 1-9, 0. os: Qt.platform.os
function digitOf(event, os) {
    if (event.key >= 0x30 && event.key <= 0x39)  // Qt.Key_0 .. Qt.Key_9
        return event.key - 0x30
    var controlOrAlt = 0x04000000 | 0x08000000  // Qt.ControlModifier | Qt.AltModifier
    if (os === "windows" && (event.modifiers & controlOrAlt) === 0
            && event.nativeScanCode >= 0x02 && event.nativeScanCode <= 0x0B)
        return (event.nativeScanCode - 1) % 10
    return -1
}
