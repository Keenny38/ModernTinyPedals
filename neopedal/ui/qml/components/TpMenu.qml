import QtQuick
import QtQuick.Controls.Basic

// Popup menu: flyout surface with a soft shadow, fades in, items highlighted on hover, check marks, separators
// (MenuSeparator {}). Menu of a button: toggleBelow(button) opens it below the button (theme gap), a second click
// on the same button closes it (instead of closing & opening again), keyboard focus back on the button after Esc.
//   TpButton { id: more; onClicked: moreMenu.toggleBelow(more); TpMenu { id: moreMenu; ... } }
//   moreMenu.toggleBelow(hudButton, true)  // right edges aligned (button at the page's right edge)
Menu {
    id: menu
    padding: 4
    // As wide as its widest item (long French labels), 13 em at least, never wider than the window. Measured
    // again when an item changes width, once after items are added or removed (Instantiator models insert them
    // one by one: measured at each insert, the cost grew with the square of the count) and when it opens
    property int measureSerial: 0
    readonly property real widestItem: {
        var widest = 0
        measureSerial  // items added or removed (not count: changes at each insert)
        for (var i = 0; ; ++i) {
            var entry = itemAt(i)
            if (!entry)
                break
            widest = Math.max(widest, entry.implicitWidth)
        }
        return widest
    }
    function measureItems() { measureSerial += 1 }
    onCountChanged: Qt.callLater(menu.measureItems)  // once per batch of inserts
    onAboutToShow: measureItems()  // items added just before opening: width right where it opens
    implicitWidth: Math.min(Math.max(theme.em * 13, widestItem + leftPadding + rightPadding),
                            parent && parent.Window.window ? parent.Window.width - theme.em : theme.em * 40)

    // Button the menu was opened from by toggleBelow (null: opened otherwise). A press on it does not close the
    // menu (close policy: outside of its parent, the button), its click then closes it: one click, one toggle.
    property Item toggleSource: null
    property bool refocusSource: false  // button had keyboard focus: given back when the menu closes
    function toggleBelow(source, alignRight) {
        if (visible) {
            close()
            if (toggleSource === source)
                return
        }
        toggleSource = source
        refocusSource = source.activeFocus === true
        measureItems()
        popup(source, alignRight === true ? source.width - Math.max(width, implicitWidth) : 0, source.height + theme.space1)
    }
    closePolicy: toggleSource !== null ? Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                                       : Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onClosed: {
        var source = toggleSource
        toggleSource = null
        if (source !== null && refocusSource)
            source.forceActiveFocus()
    }

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: theme.motionFast }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: theme.motionFast; easing.type: Easing.OutCubic }
    }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: theme.motionFast } }

    background: Rectangle {
        implicitWidth: theme.em * 13
        radius: theme.radiusLg
        color: theme.surfaceFlyout
        border.width: 1
        border.color: theme.strokeSubtle
        TpShadow {}
    }

    delegate: TpMenuItem {}
}
