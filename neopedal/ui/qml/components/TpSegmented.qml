import QtQuick
import QtQuick.Controls.Basic

// Segmented control: one option selected (a mode or a filter of the content; TpTabBar navigates between contents),
// highlight slides between options. Options: texts, or objects { text, glyph, fallback, tip } (icon & text, or
// icon only: text "" with a tip, read by screen readers & shown as tooltip; without icon font the fallback, else
// the tip is shown). Screen readers: a radio group, arrows / Home / End choose (like a tab bar).
// maxWidth > 0: options squeezed to fit (less room around texts, then smaller texts)
// name: what the options choose (screen readers: "View: Simple")
//   TpSegmented { options: [i18n.tr("Laps"), i18n.tr("Stints")]; currentIndex: page.tab; onActivated: ... }
//   TpSegmented { options: [{ glyph: "", tip: i18n.tr("Cards") }, { glyph: "", tip: i18n.tr("List") }] }
Rectangle {
    id: control
    property var options: []
    property int currentIndex: 0
    property real maxWidth: 0
    property string name: ""
    property real textsWidth: 0  // options texts at normal size
    readonly property real inset: Math.max(2, Math.round(theme.em * 0.25))  // highlight inside the frame
    readonly property real minPad: theme.em * 0.5
    readonly property real glyphSize: theme.em * 0.95
    readonly property bool squeezed: maxWidth > 0 && textsWidth > 0
    readonly property real fontScale: squeezed
        ? Math.max(Math.min(1, (maxWidth - inset * 2 - options.length * minPad) / textsWidth), 0.7) : 1
    readonly property real pad: squeezed
        ? Math.max(Math.min(theme.em * 1.6, (maxWidth - inset * 2 - textsWidth * fontScale) / Math.max(options.length, 1)), minPad)
        : theme.em * 1.6
    signal activated(int index)

    // Parts of an option (text or object)
    function optionText(option) {
        if (option === undefined || option === null)
            return ""
        return typeof option === "object" ? String(option.text || "") : String(option)
    }
    function optionGlyph(option) {
        return option && typeof option === "object" ? String(option.glyph || "") : ""
    }
    function optionTip(option) {
        return option && typeof option === "object" ? String(option.tip || "") : ""
    }
    // Text shown: its text, else (icon only, no icon font) its fallback or tip
    function shownText(option) {
        var text = optionText(option)
        if (text !== "" || optionGlyph(option) === "" || theme.iconFont !== "")
            return text
        return option.fallback ? String(option.fallback) : optionTip(option)
    }
    // Name for screen readers: text, else tip
    function optionName(option) {
        var text = optionText(option)
        return text !== "" ? text : optionTip(option)
    }

    // Option picked: caller stores it (backend or own property), currentIndex follows through its binding
    // (never set here: that would replace the caller's binding)
    function choose(index) {
        if (index < 0 || index >= options.length)
            return
        activated(index)
    }

    // Tab reaches it, arrows / Home / End choose (radio group)
    activeFocusOnTab: true
    Keys.onLeftPressed: choose(currentIndex - 1)
    Keys.onRightPressed: choose(currentIndex + 1)
    Keys.onUpPressed: choose(currentIndex - 1)
    Keys.onDownPressed: choose(currentIndex + 1)
    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Home) { choose(0); event.accepted = true }
        else if (event.key === Qt.Key_End) { choose(options.length - 1); event.accepted = true }
    }
    // Focused control takes its arrows: page shortcuts on these keys (Broadcast Director) do not fire
    Keys.onShortcutOverride: function(event) {
        if ([Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Home, Qt.Key_End].indexOf(event.key) >= 0)
            event.accepted = true
    }
    Accessible.role: Accessible.Grouping
    Accessible.name: name !== "" ? name + ": " + optionName(options[currentIndex]) : optionName(options[currentIndex])
    opacity: enabled ? 1 : theme.disabledOpacity

    // Widths from texts & glyphs (never from .visible): squeezing works inside hidden parents too
    function measure() {
        var sum = 0
        for (var i = 0; i < options.length; i++) {
            probe.text = shownText(options[i])
            sum += probe.advanceWidth + (optionGlyph(options[i]) !== "" && theme.iconFont !== ""
                                         ? glyphSize + (probe.text !== "" ? theme.space2 : 0) : 0)
        }
        textsWidth = sum
    }
    TextMetrics { id: probe; font.weight: Font.DemiBold; font.pointSize: theme.fontPoint }
    onOptionsChanged: measure()
    Component.onCompleted: measure()

    implicitHeight: Math.round(theme.controlHeight)
    implicitWidth: row.implicitWidth + inset * 2
    radius: theme.radiusSm
    color: theme.surfaceSunken
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
        radius: theme.radiusXs
        color: theme.raised
        border.width: 1
        border.color: theme.strokeSubtle
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
                id: option
                required property var modelData
                required property int index
                readonly property bool current: index === control.currentIndex
                readonly property string label: control.shownText(modelData)
                readonly property string glyph: control.optionGlyph(modelData)
                readonly property string tip: control.optionTip(modelData)
                width: optionRow.implicitWidth + control.pad
                height: row.height
                Accessible.role: Accessible.RadioButton
                Accessible.name: control.optionName(modelData)
                Accessible.description: label !== "" ? tip : ""
                Accessible.checkable: true
                Accessible.checked: current
                Accessible.onPressAction: control.choose(index)
                ToolTip.visible: tip !== "" && optionArea.containsMouse
                ToolTip.text: tip
                ToolTip.delay: theme.tipDelay
                Row {
                    id: optionRow
                    anchors.centerIn: parent
                    spacing: option.label !== "" ? theme.space2 : 0
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        glyph: option.glyph
                        size: control.glyphSize * control.fontScale
                        color: option.current ? theme.accent : optionArea.containsMouse ? theme.text : theme.dimText
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: text !== ""
                        text: option.label
                        textFormat: Text.PlainText
                        font.pointSize: theme.fontPoint * control.fontScale
                        color: option.current || optionArea.containsMouse ? theme.text : theme.dimText
                        font.weight: option.current ? Font.DemiBold : Font.Normal
                        Behavior on color { ColorAnimation { duration: theme.motionBase } }
                    }
                }
                Rectangle {  // hover, under text
                    z: -1
                    anchors.fill: parent
                    anchors.topMargin: control.inset
                    anchors.bottomMargin: control.inset
                    radius: theme.radiusXs
                    color: theme.hover
                    opacity: optionArea.containsMouse && !option.current ? 0.6 : 0
                    Behavior on opacity { NumberAnimation { duration: theme.motionFast } }
                }
                MouseArea {
                    id: optionArea
                    anchors.fill: parent
                    hoverEnabled: control.enabled
                    cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: control.choose(option.index)
                }
            }
        }
    }
}
