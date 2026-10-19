import QtQuick

// Segmented control: one option selected, highlight slides between options
// maxWidth > 0: options squeezed to fit (less room around texts, then smaller texts)
// name: what the options choose (screen readers: "View: Simple")
Rectangle {
    id: control
    property var options: []  // texts
    property int currentIndex: 0
    property real maxWidth: 0
    property string name: ""
    property real textsWidth: 0  // options texts at normal size
    readonly property real inset: Math.max(2, Math.round(theme.em * 0.25))  // highlight inside the frame
    readonly property real minPad: theme.em * 0.5
    readonly property bool squeezed: maxWidth > 0 && textsWidth > 0
    readonly property real fontScale: squeezed
        ? Math.max(Math.min(1, (maxWidth - inset * 2 - options.length * minPad) / textsWidth), 0.7) : 1
    readonly property real pad: squeezed
        ? Math.max(Math.min(theme.em * 1.6, (maxWidth - inset * 2 - textsWidth * fontScale) / Math.max(options.length, 1)), minPad)
        : theme.em * 1.6
    signal activated(int index)

    // Option picked: caller stores it (backend or own property), currentIndex follows through its binding
    // (never set here: that would replace the caller's binding)
    function choose(index) {
        if (index < 0 || index >= options.length)
            return
        activated(index)
    }

    // Tab reaches it, arrows / Home / End choose (like a tab bar)
    activeFocusOnTab: true
    Keys.onLeftPressed: choose(currentIndex - 1)
    Keys.onRightPressed: choose(currentIndex + 1)
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Home) { choose(0); event.accepted = true }
        else if (event.key === Qt.Key_End) { choose(options.length - 1); event.accepted = true }
    }
    // Focused control takes its arrows: page shortcuts on these keys (Broadcast Director) do not fire
    Keys.onShortcutOverride: function(event) {
        if ([Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End].indexOf(event.key) >= 0)
            event.accepted = true
    }
    Accessible.role: Accessible.PageTabList
    Accessible.name: name !== "" ? name + ": " + (options[currentIndex] || "") : (options[currentIndex] || "")
    opacity: enabled ? 1 : theme.disabledOpacity

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

    implicitHeight: Math.round(theme.controlHeight)
    implicitWidth: row.implicitWidth + inset * 2
    radius: theme.radiusLg
    color: theme.dark ? Qt.darker(theme.base, 1.25) : Qt.darker(theme.window, 1.04)
    border.width: 1
    border.color: theme.border

    FocusRing { visible: control.activeFocus }

    Rectangle {
        id: highlight
        property Item target: row.children[control.currentIndex] || null
        x: target ? target.x + row.x : 0
        width: target ? target.width : 0
        y: control.inset
        height: parent.height - control.inset * 2
        radius: theme.radiusMd
        color: theme.raised
        border.width: theme.dark ? 0 : 1
        border.color: theme.border
        Behavior on x { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: theme.motionSlow; easing.type: Easing.OutCubic } }
    }

    Row {
        id: row
        x: control.inset
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
                    color: index === control.currentIndex || optionArea.containsMouse ? theme.text : theme.dimText
                    font.weight: index === control.currentIndex ? Font.DemiBold : Font.Normal
                    Behavior on color { ColorAnimation { duration: theme.motionBase } }
                }
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData
                Accessible.selected: index === control.currentIndex
                Rectangle {  // hover, under text
                    z: -1
                    anchors.fill: parent
                    anchors.topMargin: control.inset
                    anchors.bottomMargin: control.inset
                    radius: theme.radiusMd
                    color: theme.hover
                    opacity: optionArea.containsMouse && index !== control.currentIndex ? 0.6 : 0
                    Behavior on opacity { NumberAnimation { duration: theme.motionFast } }
                }
                MouseArea {
                    id: optionArea
                    anchors.fill: parent
                    hoverEnabled: control.enabled
                    cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: control.choose(index)
                }
            }
        }
    }
}
