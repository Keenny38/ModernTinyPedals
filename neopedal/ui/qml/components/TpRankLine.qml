import QtQuick

// Rank over time (Home driver card, Driver Stats): line of rank values (points { x, y } 0-1: Bronze 1 at the
// bottom), last rank dotted, in the rank color; optional label on the left (labelShown). Drawn again only when
// points, size or color change.
//   TpRankLine { Layout.fillWidth: true; points: modelData.chart; tint: rankColor; label: modelData.label }
//   TpRankLine { labelShown: true; points: ...; label: modelData.label }  // name of the rank on the left
Item {
    id: rankLine
    property var points: []
    property color tint: theme.accent
    property string label: ""
    property bool labelShown: false
    property real labelWidth: theme.em * 6.5
    property real lineWidth: 2
    property real dotRadius: 3

    implicitHeight: Math.round(labelShown ? theme.em * 2 : theme.em * 1.6)
    Accessible.role: Accessible.Graphic
    Accessible.name: label
    onPointsChanged: lineCanvas.requestPaint()
    onTintChanged: lineCanvas.requestPaint()

    Text {
        id: lineLabel
        visible: rankLine.labelShown
        text: rankLine.label
        textFormat: Text.PlainText
        color: theme.dimText
        font.pointSize: theme.fontCaption
        width: rankLine.labelWidth
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
    }
    Canvas {
        id: lineCanvas
        x: rankLine.labelShown ? rankLine.labelWidth + theme.space3 : 0
        width: Math.max(0, parent.width - x)
        height: parent.height
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var points = rankLine.points || []
            if (points.length < 2)
                return
            var pad = rankLine.dotRadius, w = width - pad * 2, h = height - pad * 2
            ctx.strokeStyle = rankLine.tint
            ctx.lineWidth = rankLine.lineWidth
            ctx.lineJoin = "round"
            ctx.beginPath()
            for (var i = 0; i < points.length; i++) {
                var x = pad + points[i].x * w, y = pad + (1 - points[i].y) * h
                if (i === 0)
                    ctx.moveTo(x, y)
                else
                    ctx.lineTo(x, y)
            }
            ctx.stroke()
            var last = points[points.length - 1]
            ctx.fillStyle = rankLine.tint
            ctx.beginPath()
            ctx.arc(pad + last.x * w, pad + (1 - last.y) * h, rankLine.dotRadius, 0, Math.PI * 2)
            ctx.fill()
        }
    }
}
