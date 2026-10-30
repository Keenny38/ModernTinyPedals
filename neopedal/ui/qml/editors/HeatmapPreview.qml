import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Preview of the heatmap being edited (unsaved edits too): one band per step, from coldest to hottest, each
// with its start temperature (overlays use a step's color from its temperature up to the next one)
Item {
    id: preview
    property var bands: []  // {color, label, tip}

    implicitHeight: Math.round(theme.row)
    Accessible.role: Accessible.Graphic
    Accessible.name: i18n.tr("Heatmap preview")

    Rectangle {
        anchors.fill: parent
        radius: theme.radiusMd
        color: "transparent"
        border.width: 1
        border.color: theme.border
        visible: preview.bands.length === 0
        TpText {
            anchors.centerIn: parent
            role: "caption"
            text: i18n.tr("No temperature step")
        }
    }

    Row {
        anchors.fill: parent
        Repeater {
            model: preview.bands
            Rectangle {
                id: band
                required property var modelData
                required property int index
                width: preview.width / Math.max(1, preview.bands.length)
                height: preview.height
                color: modelData.color
                radius: index === 0 || index === preview.bands.length - 1 ? theme.radiusSm : 0
                TpText {
                    anchors.centerIn: parent
                    width: parent.width - theme.space2
                    role: "caption"
                    tabular: true
                    horizontalAlignment: Text.AlignHCenter
                    text: band.modelData.label
                    color: theme.inkOn(band.color)
                }
                HoverHandler { id: bandHover }
                TpToolTip {
                    visible: bandHover.hovered
                    text: bandHover.hovered ? band.modelData.tip : ""
                    delay: theme.tipDelay
                }
            }
        }
    }
}
