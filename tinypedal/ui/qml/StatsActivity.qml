import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Driving activity of each day: one column per week (Monday on top), the last weeks that fit the width,
// month names above, day color by driving time (accent, stronger for longer), summary & legend below.
// Activity from backend: weeks, days (level -1 future, 0 none, 1-4; tip), months (week, text), dayNames.
Item {
    id: activity

    property var activityData: ({})
    readonly property var days: activityData.days || []
    readonly property int weeks: activityData.weeks || 0
    readonly property real gap: Math.max(2, Math.round(theme.em * 0.2))
    readonly property real labelWidth: theme.em * 2.4
    // Day size: every week when it fits (up to 1.15 em), else the last weeks at 0.75 em
    readonly property real cell: Math.max(Math.round(theme.em * 0.75),
                                          Math.min(Math.floor((width - labelWidth) / Math.max(weeks, 1) - gap), Math.round(theme.em * 1.15)))
    readonly property real step: cell + gap
    readonly property real monthHeight: theme.em * 1.3
    readonly property int shownWeeks: Math.max(1, Math.min(weeks, Math.floor((width - labelWidth + gap) / step)))
    readonly property int firstDay: Math.max(0, (weeks - shownWeeks) * 7)
    property int hovered: -1

    function dayColor(level) {
        if (level < 0) return "transparent"
        if (level === 0) return theme.dark ? Qt.lighter(theme.base, 1.25) : Qt.darker(theme.base, 1.06)
        return Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, [0, 0.32, 0.52, 0.76, 1][level])
    }

    implicitHeight: monthHeight + step * 7 + theme.em * 1.9

    // Month names over the week they start in
    Repeater {
        model: activity.activityData.months || []
        Text {
            required property var modelData
            readonly property int column: modelData.week - activity.firstDay / 7
            visible: column >= 0 && column <= activity.shownWeeks - 2
            x: activity.labelWidth + column * activity.step
            y: 0
            text: modelData.text
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.78
        }
    }
    // Monday, Wednesday & Friday names
    Repeater {
        model: activity.activityData.dayNames || []
        Text {
            required property var modelData
            required property int index
            x: 0
            width: activity.labelWidth - theme.em * 0.4
            y: activity.monthHeight + index * 2 * activity.step + (activity.cell - height) / 2
            text: modelData
            color: theme.dimText
            horizontalAlignment: Text.AlignRight
            font.pointSize: theme.fontPoint * 0.72
            elide: Text.ElideRight
        }
    }
    // Days: painted at once (a year of days), hovered day outlined
    onDaysChanged: dayCanvas.requestPaint()
    onShownWeeksChanged: dayCanvas.requestPaint()
    onCellChanged: dayCanvas.requestPaint()
    readonly property var paintColors: [theme.accent, theme.base, theme.dark]  // theme switched: painted again
    onPaintColorsChanged: dayCanvas.requestPaint()
    Canvas {
        id: dayCanvas
        x: activity.labelWidth
        y: activity.monthHeight
        width: activity.shownWeeks * activity.step
        height: 7 * activity.step
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var size = activity.cell, step = activity.step, corner = Math.max(2, size * 0.22)
            for (var index = 0; index < activity.shownWeeks * 7; index++) {
                var day = activity.days[activity.firstDay + index]
                if (!day || day.level < 0) continue
                var x = Math.floor(index / 7) * step, y = (index % 7) * step
                ctx.fillStyle = activity.dayColor(day.level)
                ctx.beginPath()
                ctx.roundedRect(x, y, size, size, corner, corner)
                ctx.fill()
            }
        }
    }
    Rectangle {  // hovered day
        visible: activity.hovered >= 0
        x: activity.labelWidth + Math.floor((activity.hovered - activity.firstDay) / 7) * activity.step - 1
        y: activity.monthHeight + ((activity.hovered - activity.firstDay) % 7) * activity.step - 1
        width: activity.cell + 2
        height: width
        radius: Math.max(2, activity.cell * 0.22) + 1
        color: "transparent"
        border.width: 1.5
        border.color: theme.text
    }
    MouseArea {
        id: dayArea
        x: activity.labelWidth
        y: activity.monthHeight
        width: activity.shownWeeks * activity.step
        height: 7 * activity.step
        hoverEnabled: true
        onPositionChanged: function(mouse) {
            var column = Math.floor(mouse.x / activity.step), row = Math.floor(mouse.y / activity.step)
            var index = activity.firstDay + column * 7 + row
            var day = activity.days[index]
            activity.hovered = row < 7 && day && day.level >= 0 ? index : -1
        }
        onExited: activity.hovered = -1
    }
    ToolTip {
        parent: activity
        visible: activity.hovered >= 0
        text: visible ? activity.days[activity.hovered].tip : ""
        delay: 150
        x: visible ? Math.max(0, Math.min(activity.labelWidth + Math.floor((activity.hovered - activity.firstDay) / 7) * activity.step
                                          - width / 2, activity.width - width)) : 0
        y: visible ? activity.monthHeight + ((activity.hovered - activity.firstDay) % 7) * activity.step - height - 4 : 0
    }

    // Summary & legend
    RowLayout {
        y: activity.monthHeight + 7 * activity.step + theme.em * 0.45
        width: activity.width
        spacing: theme.em * 0.3
        Text {
            text: activity.activityData.summary || ""
            color: theme.dimText
            font.pointSize: theme.fontPoint * 0.85
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
        Text { text: i18n.tr("Less"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.78 }
        Repeater {
            model: 5
            Rectangle {
                required property int index
                width: activity.cell * 0.85
                height: width
                radius: Math.max(2, width * 0.22)
                color: activity.dayColor(index)
            }
        }
        Text { text: i18n.tr("More"); color: theme.dimText; font.pointSize: theme.fontPoint * 0.78 }
    }
}
