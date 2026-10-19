import QtQuick

// Action of a TpToolbar: shown as a button, icon only, or as an entry of the toolbar's "⋯" menu when room
// runs out (least important first: lower priority). triggered(source): button or "⋯" button it came from,
// to open a popup next to it.
//   TpAction { name: "exportButton"; text: i18n.tr("Export"); glyph: ""; priority: 1
//              onTriggered: function(source) { exportMenu.popup(source, 0, source.height) } }
QtObject {
    property string name: ""  // objectName of the button (tests, scripts)
    property string text: ""
    property string glyph: ""
    property string fallback: ""  // short text without icon font
    property string tip: ""
    property int priority: 0  // higher: keeps its text & its button longer
    property bool shown: true
    property bool enabled: true
    property bool checkable: false
    property bool checked: false
    property bool accent: false
    property bool flat: false
    property bool pinned: false  // never moved into the menu (may still lose its text)
    signal triggered(var source)
}
