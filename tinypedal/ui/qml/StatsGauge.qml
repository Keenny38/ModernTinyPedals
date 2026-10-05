import QtQuick
import QtQuick.Controls.Basic

// Level scale of selected vehicle: levels from slowest (left) to fastest (right) in their colors, level of
// personal best lit, marks of personal best (round, with its label) & of qualifying / race bests (diamonds).
// Marks slide when selection changes. Hover a level: name & lap time limit; hover a mark: lap time & level.
Item {
    id: gauge

    property var scaleData: ({})  // segments (name, letter, color, limit), markers (label, short, main, pos, time, color, tip)
    readonly property var segments: scaleData.segments || []
    readonly property var markers: scaleData.markers || []
    readonly property real barY: theme.em * 1.75
    readonly property real barHeight: Math.round(theme.em * 0.7)
    readonly property real gap: 3
    readonly property real segmentWidth: segments.length ? (width - gap * (segments.length - 1)) / segments.length : 0
    readonly property real mainPos: {  // personal best position, -1 if none
        for (var i = 0; i < markers.length; i++) {
            if (markers[i].main) return markers[i].pos
        }
        return -1
    }
    readonly property int litSegment: {  // level of personal best
        for (var i = 0; i < markers.length; i++) {
            if (markers[i].main) return Math.min(Math.floor(markers[i].pos * segments.length), segments.length - 1)
        }
        return -1
    }

    implicitHeight: barY + barHeight + theme.em * 1.55

    Repeater {
        model: gauge.segments
        Item {
            id: segment
            required property var modelData
            required property int index
            readonly property bool lit: index === gauge.litSegment
            x: index * (gauge.segmentWidth + gauge.gap)
            y: gauge.barY
            width: gauge.segmentWidth
            height: gauge.barHeight + theme.em * 1.5
            Rectangle {
                width: parent.width
                height: gauge.barHeight
                radius: height / 2
                color: segment.modelData.color
                opacity: segment.lit ? 1 : gauge.litSegment < 0 ? 0.7 : 0.42
                Behavior on opacity { NumberAnimation { duration: 260 } }
            }
            Text {
                y: gauge.barHeight + theme.em * 0.25
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: segment.modelData.letter
                color: segment.lit ? segment.modelData.color : theme.dimText
                font.pointSize: theme.fontPoint * 0.8
                font.weight: segment.lit ? Font.Bold : Font.Normal
            }
            HoverHandler { id: segmentHover }
            ToolTip.visible: segmentHover.hovered
            ToolTip.text: segment.modelData.name + "  " + segment.modelData.limit
            ToolTip.delay: 300
        }
    }

    Repeater {  // marks kept while their count is the same: they slide to their new place
        model: gauge.markers.length
        Item {
            id: marker
            required property int index
            readonly property var mark: gauge.markers[index] || ({})
            property real centerX: Math.max(0, Math.min(mark.pos || 0, 1)) * gauge.width
            x: centerX - width / 2
            y: 0
            width: theme.em * 1.6
            height: gauge.barY + gauge.barHeight + theme.em * 0.3
            z: mark.main ? 2 : 1
            Behavior on centerX { NumberAnimation { duration: 380; easing.type: Easing.OutCubic } }

            Text {  // label: personal best name, else first letter (hidden next to personal best label)
                visible: marker.mark.main === true || gauge.mainPos < 0
                         || Math.abs((marker.mark.pos || 0) - gauge.mainPos) * gauge.width > theme.em * 2.4
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                text: (marker.mark.main ? marker.mark.label : marker.mark.short) || ""
                color: marker.mark.main ? theme.text : theme.dimText
                font.pointSize: theme.fontPoint * (marker.mark.main ? 0.85 : 0.78)
                font.weight: marker.mark.main ? Font.Bold : Font.DemiBold
            }
            Rectangle {  // qualifying / race best: diamond above bar
                visible: !marker.mark.main
                width: theme.em * 0.55
                height: width
                rotation: 45
                anchors.horizontalCenter: parent.horizontalCenter
                y: gauge.barY - height * 0.9
                color: theme.text
                opacity: 0.75
            }
            Rectangle {  // personal best: round mark on bar
                visible: marker.mark.main
                width: Math.round(theme.em * 1.2)
                height: width
                radius: width / 2
                anchors.horizontalCenter: parent.horizontalCenter
                y: gauge.barY + (gauge.barHeight - height) / 2
                color: marker.mark.color || theme.accent
                border.width: Math.max(2, Math.round(theme.em * 0.16))
                border.color: theme.base
                Behavior on color { ColorAnimation { duration: 260 } }
            }
            HoverHandler { id: markerHover }
            ToolTip.visible: markerHover.hovered
            ToolTip.text: marker.mark.tip || ""
            ToolTip.delay: 200
        }
    }
}
