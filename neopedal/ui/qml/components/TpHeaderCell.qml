import QtQuick
import QtQuick.Controls.Basic

// Column header of a table: caption (dim, small capitals), optional sort with click, Enter or Space and a
// ▲ / ▼ mark (plain characters: shown without icon font too), tooltip. align: Qt.AlignRight for numbers.
//   TpHeaderCell { text: i18n.tr("Laps"); align: Qt.AlignRight; sortable: true; sorted: page.sortKey === "laps";
//                  descending: page.sortDescending; onSortRequested: backend.sortBy("laps") }
AbstractButton {
    id: cell
    property string tip: ""
    property int align: Qt.AlignLeft
    property bool sortable: false
    property bool sorted: false
    property bool descending: false
    signal sortRequested()

    hoverEnabled: sortable || tip !== "" || label.truncated
    focusPolicy: sortable ? Qt.TabFocus : Qt.NoFocus
    implicitHeight: Math.round(theme.headerHeight)
    implicitWidth: label.implicitWidth + (sorted ? arrow.implicitWidth + theme.space1 : 0) + theme.space3
    onClicked: if (sortable) sortRequested()
    Keys.onReturnPressed: if (sortable) sortRequested()
    Keys.onEnterPressed: if (sortable) sortRequested()

    Accessible.role: Accessible.ColumnHeader
    Accessible.name: text + (sorted ? ", " + (descending ? i18n.tr("Sorted descending") : i18n.tr("Sorted ascending")) : "")
    Accessible.description: tip
    ToolTip.visible: (tip !== "" || label.truncated) && hovered
    ToolTip.text: tip !== "" ? (label.truncated ? text + "\n" + tip : tip) : text
    ToolTip.delay: theme.tipDelay

    HoverHandler { cursorShape: cell.sortable ? Qt.PointingHandCursor : Qt.ArrowCursor }

    background: Rectangle {
        radius: theme.radiusSm
        color: cell.sortable && cell.hovered ? theme.hover : "transparent"
        Behavior on color { ColorAnimation { duration: theme.motionFast } }
        FocusRing { visible: cell.visualFocus }
    }
    contentItem: Item {
        Row {
            id: row
            spacing: theme.space1
            anchors.verticalCenter: parent.verticalCenter
            x: cell.align & Qt.AlignRight ? parent.width - width - theme.space1
             : cell.align & Qt.AlignHCenter ? (parent.width - width) / 2 : theme.space1
            // From the texts' natural widths (Row's own implicit width follows the cut label: loop), 1 px more: a short
            // caption given exactly its fractional width is elided ("PB" shown "...")
            width: Math.min(label.implicitWidth + 1 + (cell.sorted ? arrow.implicitWidth + spacing : 0), parent.width - theme.space2)
            Text {
                id: label
                text: cell.text
                textFormat: Text.PlainText
                width: Math.max(0, Math.min(implicitWidth + 1, row.width - (cell.sorted ? arrow.width + row.spacing : 0)))
                elide: Text.ElideRight
                color: cell.sorted ? theme.accent : theme.dimText
                font.pointSize: theme.fontCaption
                font.weight: Font.DemiBold
                font.capitalization: Font.AllUppercase
                font.letterSpacing: theme.letterSpacingOverline  // capitals, as overline texts
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                id: arrow
                visible: cell.sorted
                text: cell.descending ? "▼" : "▲"
                textFormat: Text.PlainText
                color: theme.accent
                font.pointSize: theme.fontMicro
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
