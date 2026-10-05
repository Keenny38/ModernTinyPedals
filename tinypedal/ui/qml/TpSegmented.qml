import QtQuick

// Segmented control: one option selected, highlight slides between options
// maxWidth > 0: options squeezed to fit (less room around texts, then smaller texts)
Rectangle {
    id: control
    property var options: []  // texts
    property int currentIndex: 0
    property real maxWidth: 0
    property real textsWidth: 0  // options texts at normal size
    readonly property real minPad: theme.em * 0.5
    readonly property bool squeezed: maxWidth > 0 && textsWidth > 0
    readonly property real fontScale: squeezed
        ? Math.max(Math.min(1, (maxWidth - 6 - options.length * minPad) / textsWidth), 0.7) : 1
    readonly property real pad: squeezed
        ? Math.max(Math.min(theme.em * 1.6, (maxWidth - 6 - textsWidth * fontScale) / Math.max(options.length, 1)), minPad)
        : theme.em * 1.6
    signal activated(int index)

    function measure() {
        var sum = 0
        for (var i = 0; i < options.length; i++) {
            probe.text = options[i]
            sum += probe.advanceWidth
        }
        textsWidth = sum
    }
    TextMetrics { id: probe; font.weight: Font.DemiBold; font.pointSize: theme.fontPoint }
    onOptionsChanged: measure()
    Component.onCompleted: measure()

    implicitHeight: Math.round(theme.em * 2.3)
    implicitWidth: row.implicitWidth + 6
    radius: theme.em * 0.6
    color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
    border.width: 1
    border.color: theme.border

    Rectangle {
        id: highlight
        property Item target: row.children[control.currentIndex] || null
        x: target ? target.x + row.x : 0
        width: target ? target.width : 0
        y: 3
        height: parent.height - 6
        radius: theme.em * 0.45
        color: theme.raised
        border.width: theme.dark ? 0 : 1
        border.color: theme.border
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }

    Row {
        id: row
        x: 3
        height: parent.height
        Repeater {
            model: control.options
            Item {
                width: optionText.implicitWidth + control.pad
                height: row.height
                Text {
                    id: optionText
                    anchors.centerIn: parent
                    text: modelData
                    font.pointSize: theme.fontPoint * control.fontScale
                    color: index === control.currentIndex ? theme.text : theme.dimText
                    font.weight: index === control.currentIndex ? Font.DemiBold : Font.Normal
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: { control.currentIndex = index; control.activated(index) }
                }
            }
        }
    }
}
