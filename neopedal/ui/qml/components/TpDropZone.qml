import QtQuick

// Files dropped on a page: drop area filling its parent, accent outline & tint with an icon and what a drop does
// while files are dragged over it. accepts(urls): files taken (false: drag refused, no outline), filesDropped(urls)
// after the drop is over (a dialog or a warning may open then).
//   TpDropZone { anchors.fill: parent; text: i18n.tr("Drop replays (.Vcr) to add them to the game")
//                onFilesDropped: function(urls) { replays.addFiles(urls) } }
DropArea {
    id: zone
    property string text: ""
    property var accepts: null  // function(urls) returning true when the files are taken, null: any file
    signal filesDropped(var urls)

    onEntered: function(drag) { drag.accepted = drag.hasUrls && (zone.accepts === null || zone.accepts(drag.urls)) }
    onDropped: function(drop) {
        if (!drop.hasUrls) return
        drop.acceptProposedAction()
        var urls = drop.urls
        Qt.callLater(function() { zone.filesDropped(urls) })  // dialogs & warnings once the drop is over
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: theme.space3
        visible: zone.containsDrag
        radius: theme.radiusLg
        color: theme.tint(theme.accent, "subtle")
        border.width: 2
        border.color: theme.accent
        Column {
            anchors.centerIn: parent
            width: parent.width - theme.space6 * 2
            spacing: theme.space4
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                glyph: ""  // download
                fallback: "↓"
                size: theme.iconHero
                color: theme.accent
            }
            TpText {
                width: parent.width
                role: "subtitle"
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                text: zone.text
                font.pointSize: theme.fontHeading
            }
        }
    }
}
