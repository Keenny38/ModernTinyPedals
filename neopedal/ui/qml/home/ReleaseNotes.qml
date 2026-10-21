import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// What's New page: version header & version menu (any version of the local changelog), search, contents chips
// (versions or groups), notes as one list (version headers, group headings, cards, folds), download progress
// & install actions. Screenshots open in the viewer (arrows browse, Esc closes). Ctrl+F searches.
TpPage {
    id: page

    function jumpTo(key) {
        const row = backend.rowOf(key)
        if (row >= 0)
            notes.positionViewAtIndex(row, ListView.Beginning)
    }

    Shortcut { sequence: "Ctrl+F"; enabled: pageState.active; onActivated: search.forceActiveFocus() }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: theme.padPage
        spacing: theme.space3

        // Version, its state, release date, version menu
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            Text {
                text: backend.title
                color: theme.text
                font.pointSize: theme.fontTitle
                font.weight: Font.DemiBold
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Pill {
                Layout.alignment: Qt.AlignVCenter
                visible: backend.chip !== ""
                text: backend.chip
                tint: backend.chipNew ? theme.gain : theme.accent
            }
            Item { Layout.fillWidth: true }
            TpCombo {
                id: versionMenu
                Layout.preferredWidth: theme.em * 13
                visible: count > 1
                model: backend.versions
                textRole: "label"
                tip: i18n.tr("Show the notes of another version")
                currentIndex: {
                    const choices = backend.versions
                    for (let index = 0; index < choices.length; index++)
                        if (choices[index].key === backend.view)
                            return index
                    return 0
                }
                onActivated: function(index) { backend.showVersion(backend.versions[index].key) }
            }
        }
        Text {
            Layout.fillWidth: true
            visible: text !== ""
            text: backend.detail
            color: theme.dimText
            elide: Text.ElideRight
        }

        TpSearchField {
            id: search
            Layout.fillWidth: true
            placeholderText: i18n.tr("Search the notes")
            onSearchChanged: function(text) { backend.setSearch(text) }
            onExitField: notes.forceActiveFocus()
        }

        Flow {
            Layout.fillWidth: true
            visible: backend.contents.length > 0 && !backend.searching
            spacing: theme.space2
            Repeater {
                model: backend.contents
                TpChip {
                    required property var modelData
                    text: modelData.label
                    size: "sm"
                    tip: i18n.tr("Go to this part")
                    onClicked: page.jumpTo(modelData.key)
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: notes
                anchors.fill: parent
                clip: true
                model: backend.notes
                spacing: theme.space3
                boundsBehavior: Flickable.StopAtBounds
                activeFocusOnTab: true
                cacheBuffer: Math.max(height, 0)  // screenshots of the next screen loaded once the visible ones are
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Loader {
                    id: row
                    required property string key
                    required property string kind
                    required property string title
                    required property string subtitle
                    required property var items
                    required property var overlays
                    required property bool expanded
                    required property int count
                    required property int index
                    width: ListView.view.width - theme.space2
                    sourceComponent: kind === "card" ? cardRow : kind === "fold" ? foldRow
                                   : kind === "version" ? versionRow : groupRow

                    Component {
                        id: cardRow
                        ReleaseCard {
                            title: row.title
                            items: row.items
                            overlays: row.overlays
                            onImageOpened: function(url) { viewer.show(url) }
                        }
                    }
                    Component {
                        id: groupRow
                        Text {
                            topPadding: theme.space2
                            text: row.title
                            textFormat: Text.StyledText
                            color: theme.text
                            font.pointSize: theme.fontHeading
                            font.weight: Font.DemiBold
                            wrapMode: Text.Wrap
                            Accessible.role: Accessible.Heading
                            Accessible.name: text
                        }
                    }
                    Component {
                        id: versionRow
                        ColumnLayout {
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.bottomMargin: theme.space3
                                visible: row.index > 0
                                implicitHeight: 1
                                color: theme.border
                            }
                            RowLayout {
                                spacing: theme.space3
                                Text {
                                    text: row.title
                                    color: theme.accent
                                    font.pointSize: theme.fontLarge
                                    font.weight: Font.DemiBold
                                    Accessible.role: Accessible.Heading
                                    Accessible.name: text
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: row.subtitle
                                    color: theme.dimText
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                    Component {
                        id: foldRow
                        RowLayout {
                            spacing: theme.space2
                            TpButton {
                                flat: true
                                size: "sm"
                                glyph: row.expanded ? "" : ""  // chevron down, chevron right
                                fallback: row.expanded ? "▾" : "▸"
                                text: row.title
                                tip: row.expanded ? i18n.tr("Hide") : i18n.tr("Show")
                                Accessible.role: Accessible.CheckBox
                                Accessible.checked: row.expanded
                                onClicked: backend.toggleFold(row.key)
                            }
                            Pill {
                                text: "" + row.count
                                tint: theme.dimText
                                size: "sm"
                            }
                            Text {
                                Layout.fillWidth: true
                                visible: row.subtitle !== ""
                                text: row.subtitle
                                color: theme.dimText
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Keys.onPressed: function(event) {
                    if (search.routeTyped(event))
                        event.accepted = true
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: notes.count === 0
                glyph: backend.searching ? "" : ""  // search, list
                title: backend.searching ? i18n.tr("Nothing found in these notes") : i18n.tr("No release notes for this version.")
                text: backend.searching ? i18n.tr("Check spelling, or try fewer or other words.") : ""
                actionText: backend.searching ? i18n.tr("Clear Search") : ""
                onAction: { search.text = ""; backend.setSearch("") }
            }
        }

        TpNotice {
            Layout.fillWidth: true
            visible: backend.portableNote !== ""
            tone: theme.accent
            glyph: ""  // info
            fallback: "i"
            text: backend.portableNote
        }

        // Download of installer: progress & cancel
        RowLayout {
            Layout.fillWidth: true
            visible: backend.downloading
            spacing: theme.space3
            Text {
                text: backend.progressText
                color: theme.text
                font.features: { "tnum": 1 }
            }
            ProgressBar {
                id: progress
                Layout.fillWidth: true
                from: 0
                to: 1
                value: Math.max(backend.progress, 0)
                indeterminate: backend.progress < 0
                Accessible.name: i18n.tr("Download progress")
                Accessible.description: backend.progressText
            }
            TpButton {
                text: i18n.tr("Cancel Download")
                enabled: !backend.cancelling
                onClicked: backend.cancelDownload()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.space3
            TpButton {
                text: i18n.tr("View On GitHub")
                glyph: ""  // globe
                onClicked: backend.openGitHub()
            }
            TpButton {
                visible: backend.skipVisible
                enabled: !backend.downloading
                text: i18n.tr("Skip This Version")
                tip: i18n.tr("Not shown again for this version, shown again for a newer one")
                onClicked: backend.skip()
            }
            TpSwitch {
                checkable: false
                checked: backend.showAfterUpdate
                text: i18n.tr("Show after each update")
                tip: i18n.tr("What's new is shown once at the first start of a new version")
                onClicked: backend.setShowAfterUpdate(!backend.showAfterUpdate)
                Accessible.role: Accessible.CheckBox
                Accessible.name: i18n.tr("Show after each update")
                Accessible.checked: backend.showAfterUpdate
            }
            Item { Layout.fillWidth: true }
            TpButton {
                visible: backend.closeVisible
                text: backend.closeText
                onClicked: backend.close()
            }
            TpButton {
                visible: backend.installVisible
                enabled: !backend.downloading
                accent: true
                text: backend.installText
                tip: backend.installTip
                onClicked: backend.install()
            }
        }
    }

    ReleaseViewer {
        id: viewer
        anchors.fill: parent
    }
}
