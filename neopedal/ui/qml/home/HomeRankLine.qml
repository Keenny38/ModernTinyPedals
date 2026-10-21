import QtQuick

// Rank over time of Home driver card: line of rank values (x, y 0-1: Bronze 1 at the bottom), last rank dotted,
// in the rank color. Drawn again only when points, size or color change.
Canvas {
    id: line
    property var points: []
    property color tint: theme.accent
    property string label: ""
    implicitHeight: Math.round(theme.em * 1.6)
    Accessible.role: Accessible.Graphic
    Accessible.name: label
    onPointsChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onTintChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var points = line.points || []
        if (points.length < 2)
            return
        var pad = 3, w = width - pad * 2, h = height - pad * 2
        ctx.strokeStyle = line.tint
        ctx.lineWidth = 2
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
        ctx.fillStyle = line.tint
        ctx.beginPath()
        ctx.arc(pad + last.x * w, pad + (1 - last.y) * h, 3, 0, Math.PI * 2)
        ctx.fill()
    }
}
