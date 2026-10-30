import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Notification center (popup of the bell in the navigation rail): notices shown in the status band now, then
// messages of the app, newest first, with level (icon, color & word), time, repeat count and actions (View Log,
// Create Bug Report, What's New...). Messages are marked read once it closes. Esc closes it.
TpPage {
    id: page
    color: theme.surfaceFlyout  // popup window: native drop shadow of Windows popups around it
    border.width: 1
    border.color: theme.strokeSubtle
    focus: true
    Keys.onEscapePressed: backend.close()

    function severityLabel(severity) {
        return severity === "error" ? i18n.tr("Error") : severity === "warning" ? i18n.tr("Warning") : i18n.tr("Info")
    }
    function severityColor(severity) {
        return severity === "error" ? theme.loss : severity === "warning" ? theme.warning : theme.accent
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padCard
        spacing: theme.space3

        TpCardHeader {
            level: "popup"
            glyph: ""  // bell
            title: i18n.tr("Notifications")
            count: backend.entryCount > 0 ? "" + backend.entryCount : ""
            TpButton {
                visible: backend.entryCount > 0
                flat: true
                size: "sm"
                text: i18n.tr("Clear All")
                onClicked: backend.clearAll()
            }
            closable: true
            closeTip: i18n.tr("Close") + " (Esc)"
            onClosed: backend.close()
        }

        // Notices shown in the status band now
        TpSectionLabel {
            Layout.fillWidth: true
            visible: backend.active.length > 0
            text: i18n.tr("Now")
        }
        Repeater {
            model: backend.active
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: theme.space3
                Icon { glyph: ""; fallback: "i"; color: theme.accent; size: theme.iconSm }  // info
                TpText {
                    Layout.fillWidth: true
                    text: modelData.text
                    textFormat: Text.PlainText
                    color: theme.text
                    elide: Text.ElideRight
                }
                TpButton {
                    visible: modelData.key !== ""
                    size: "sm"
                    flat: true
                    text: i18n.tr("Open")
                    onClicked: backend.runAction(modelData.key)
                }
            }
        }

        TpSectionLabel {
            Layout.fillWidth: true
            Layout.topMargin: backend.active.length > 0 ? theme.space3 : 0
            visible: backend.entryCount > 0
            text: i18n.tr("Messages")
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: count > 0
            clip: true
            spacing: theme.space2
            model: backend.messages  // synced in place: a new message inserts one row, a read mark changes one
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: TpListRow {  // unread: tinted in its level color
                id: row
                required property int entryId
                required property string text
                required property string severity
                required property int count
                required property string time
                required property bool read
                required property var actions
                width: list.width
                implicitHeight: rowContent.implicitHeight + theme.padCard * 2
                card: true
                emphasized: !read
                tint: page.severityColor(severity)
                Accessible.role: Accessible.StaticText
                Accessible.name: page.severityLabel(severity) + ", " + time + ": " + text

                ColumnLayout {
                    id: rowContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: theme.padCard
                    spacing: theme.space2
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: theme.space3
                        Icon {
                            glyph: row.severity === "info" ? "" : ""  // info, warning
                            fallback: row.severity === "info" ? "i" : "!"
                            color: page.severityColor(row.severity)
                            size: theme.iconSm
                        }
                        TpText {
                            role: "label"
                            font.weight: Font.DemiBold
                            text: page.severityLabel(row.severity)
                        }
                        TpText {
                            Layout.fillWidth: true
                            role: "caption"
                            tabular: true
                            color: theme.dimOn(row.color)
                            text: row.time + (row.count > 1 ? "  ×" + row.count : "")
                        }
                        TpButton {
                            flat: true
                            size: "xs"
                            glyph: theme.glyphs.remove
                            fallback: "✕"
                            tip: i18n.tr("Remove")
                            onClicked: backend.remove(row.entryId)
                        }
                    }
                    TpText {
                        Layout.fillWidth: true
                        text: row.text
                        wrapMode: Text.Wrap
                        elide: Text.ElideNone
                    }
                    Flow {
                        Layout.fillWidth: true
                        visible: row.actions.length > 0
                        spacing: theme.space3
                        Repeater {
                            model: row.actions
                            TpButton {
                                required property var modelData
                                size: "sm"
                                text: modelData.label
                                onClicked: backend.runAction(modelData.key)
                            }
                        }
                    }
                }
            }
        }
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: backend.entryCount === 0
            TpStateView {
                anchors.centerIn: parent
                empty: true
                compact: true
                glyph: ""  // bell
                title: i18n.tr("No notifications")
                text: i18n.tr("Errors of background tasks, saving problems and updates found are kept here.")
            }
        }
    }
}
