import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Track selector: selected track, popup with search field (part of name) & tracks with last driven date,
// All Tracks first. Up / Down move in list, Enter selects, Escape closes.
AbstractButton {
    id: picker

    property string filter: ""
    readonly property var shown: {
        var words = filter.toLowerCase().trim()
        var result = []
        for (var i = 0; i < backend.tracks.length; i++) {
            var entry = backend.tracks[i]
            if (words === "" || entry.label.toLowerCase().indexOf(words) >= 0) result.push(entry)
        }
        return result
    }

    function choose(entry) {
        popup.close()
        if (entry) backend.selectTrack(entry.key)
    }

    implicitHeight: Math.round(theme.em * 2.3)
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    onClicked: popup.visible ? popup.close() : popup.open()

    background: Rectangle {
        radius: theme.em * 0.55
        color: picker.hovered ? theme.hover : theme.raised
        border.width: 1
        border.color: popup.visible ? theme.accent : theme.border
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    contentItem: RowLayout {
        spacing: theme.em * 0.5
        Icon { glyph: ""; color: theme.accent; Layout.leftMargin: theme.em * 0.6 }  // map pin
        Text {
            text: backend.currentLabel
            color: theme.text
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Icon {
            glyph: ""  // chevron down
            size: theme.em * 0.75
            color: theme.dimText
            Layout.rightMargin: theme.em * 0.6
        }
    }

    Popup {
        id: popup
        y: picker.height + 4
        width: Math.max(picker.width, theme.em * 24)
        padding: 6
        focus: true
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }
        exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 100 } }
        onOpened: {
            search.text = ""
            picker.filter = ""
            list.currentIndex = Math.max(0, picker.shown.findIndex(function(entry) { return entry.key === backend.currentTrack }))
            search.forceActiveFocus()
        }
        background: Rectangle {
            radius: theme.em * 0.6
            color: theme.raised
            border.width: 1
            border.color: theme.border
        }
        contentItem: ColumnLayout {
            spacing: 4
            TextField {
                id: search
                Layout.fillWidth: true
                implicitHeight: Math.round(theme.em * 2.1)
                placeholderText: i18n.tr("Search track...")
                color: theme.text
                placeholderTextColor: theme.dimText
                onTextEdited: {
                    picker.filter = text
                    list.currentIndex = 0
                }
                Keys.onDownPressed: list.currentIndex = Math.min(list.currentIndex + 1, list.count - 1)
                Keys.onUpPressed: list.currentIndex = Math.max(list.currentIndex - 1, 0)
                Keys.onReturnPressed: picker.choose(picker.shown[list.currentIndex])
                Keys.onEnterPressed: picker.choose(picker.shown[list.currentIndex])
                Keys.onEscapePressed: popup.close()
                background: Rectangle {
                    radius: theme.em * 0.45
                    color: theme.base
                    border.width: 1
                    border.color: search.activeFocus ? theme.accent : theme.border
                }
            }
            ListView {
                id: list
                Layout.fillWidth: true
                implicitHeight: Math.min(contentHeight, theme.em * 24)
                clip: true
                model: picker.shown
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: entryItem
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: theme.em * 2.2
                    highlighted: ListView.isCurrentItem || hovered
                    onClicked: picker.choose(modelData)
                    contentItem: RowLayout {
                        spacing: theme.em * 0.5
                        Text {
                            text: entryItem.modelData.label
                            color: theme.text
                            font.weight: entryItem.modelData.key === backend.currentTrack ? Font.DemiBold : Font.Normal
                            font.italic: entryItem.modelData.key === ""
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Icon {
                            visible: entryItem.modelData.current
                            glyph: ""  // flag: track of running session
                            size: theme.em * 0.8
                            color: theme.accent
                        }
                        Text {
                            text: entryItem.modelData.date === "-" ? "" : entryItem.modelData.date
                            color: theme.dimText
                            font.pointSize: theme.fontPoint * 0.85
                            font.features: { "tnum": 1 }
                        }
                    }
                    background: Rectangle {
                        radius: theme.em * 0.4
                        color: entryItem.highlighted ? theme.hover : "transparent"
                    }
                }
            }
            Text {
                visible: list.count === 0
                text: i18n.tr("No track found")
                color: theme.dimText
                Layout.margins: theme.em * 0.4
            }
        }
    }
}
