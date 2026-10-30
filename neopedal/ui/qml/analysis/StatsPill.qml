import QtQuick
import "../components"

// Small colored label of the driver stats cards: session type, race result, level (shared Pill look, hidden
// without text)
Pill {
    property bool strong: false  // result: told by its text (P1, DNF), the tint only adds to it
    visible: text !== ""
}
