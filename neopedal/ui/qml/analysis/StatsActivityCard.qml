import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Daily driving activity of All Tracks: calendar of days, or driving time by track & class
TpSectionCard {
    id: card
    title: i18n.tr("Activity")
    glyph: ""  // calendar
    tip: i18n.tr("Driving time of each day, all tracks")
    actions: [
        TpSegmented {
            objectName: "activityView"
            name: i18n.tr("Activity")
            options: [i18n.tr("Days"), i18n.tr("Breakdown")]
            currentIndex: backend.activityView
            onActivated: function(index) { backend.setActivityView(index) }
        },
        TpCombo {
            objectName: "activityYear"
            readonly property var years: (backend.activity.years || []).map(function(entry) { return entry.text })
            implicitWidth: theme.em * 11
            tip: i18n.tr("Period shown")
            model: years
            currentIndex: backend.activity.yearIndex || 0
            onActivated: function(index) { backend.setActivityYear(index) }
        }
    ]
    StatsActivity {
        visible: backend.activityView === 0
        Layout.fillWidth: true
        activityData: backend.activity
    }
    GridLayout {  // driving time of the period by track & by class
        visible: backend.activityView === 1 && (backend.activity.tracks || []).length > 0
        Layout.minimumHeight: theme.em * 9  // as tall as the calendar of days: no jump when switching
        Layout.fillWidth: true
        Layout.topMargin: theme.space2
        columns: width > theme.em * 40 ? 2 : 1  // content-tuned: two lists of names, bars & times
        columnSpacing: theme.space5
        rowSpacing: theme.space3
        // made again only when the activity changes
        readonly property var lists: [{ "title": i18n.tr("Driving time by track"), "rows": backend.activity.tracks || [] },
                                      { "title": i18n.tr("Driving time by class"), "rows": backend.activity.classes || [] }]
        Repeater {
            model: parent.lists
            ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                spacing: theme.space1
                StatsLabel { text: modelData.title; Layout.topMargin: 0 }
                Repeater {
                    model: modelData.rows
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Text {
                            text: modelData.name
                            textFormat: Text.PlainText
                            color: theme.text
                            elide: Text.ElideRight
                            Layout.preferredWidth: theme.em * 11
                        }
                        TpMeter {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            value: Math.max(modelData.ratio, 0.03)
                            tint: theme.accent
                            name: modelData.name
                        }
                        Text {
                            text: modelData.time
                            textFormat: Text.PlainText
                            color: theme.text
                            font.features: { "tnum": 1 }
                            Layout.preferredWidth: theme.em * 5.4
                            horizontalAlignment: Text.AlignRight
                        }
                        Text {
                            text: modelData.share
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                            Layout.preferredWidth: theme.em * 3
                            horizontalAlignment: Text.AlignRight
                        }
                    }
                }
            }
        }
    }
    Text {  // breakdown of a period without driving
        visible: backend.activityView === 1 && (backend.activity.tracks || []).length === 0
        text: backend.activity.summary || ""
        textFormat: Text.PlainText
        color: theme.dimText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
}
