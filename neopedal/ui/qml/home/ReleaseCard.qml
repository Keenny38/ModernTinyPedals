import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Card of release notes: theme title, bullets (sub-bullets indented) & paragraphs, screenshots in notes order,
// then Try / Options buttons of overlays named by the title. Links: option keys open their option (tooltip
// names it), web links open in browser.
Card {
    id: card
    property string title: ""
    property var items: []
    property var overlays: []
    signal imageOpened(string url)

    implicitHeight: column.implicitHeight + theme.padCard * 2

    function openLink(link) { backend.openLink(link, card.overlays.join(",")) }

    component NotesText: Text {
        id: notesText
        color: theme.text
        linkColor: theme.accent
        textFormat: Text.RichText
        wrapMode: Text.Wrap
        onLinkActivated: function(link) { card.openLink(link) }
        ToolTip.visible: hoveredLink !== ""
        ToolTip.delay: theme.tipDelay
        ToolTip.text: ToolTip.visible ? backend.optionTip(hoveredLink) : ""
        HoverHandler { cursorShape: notesText.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }
    }

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: theme.padCard
        spacing: theme.space2

        NotesText {
            Layout.fillWidth: true
            visible: card.title !== ""
            text: card.title
            font.pointSize: theme.fontSubtitle
            font.weight: Font.DemiBold
            Accessible.role: Accessible.Heading
            Accessible.name: card.title.replace(/<[^>]*>/g, "")
        }

        Repeater {
            model: card.items
            Loader {
                id: entry
                required property var modelData
                Layout.fillWidth: true
                Layout.leftMargin: entry.modelData.level * theme.space5
                sourceComponent: entry.modelData.image !== "" ? shot : line

                Component {
                    id: shot
                    ReleaseImage {
                        url: entry.modelData.image
                        caption: entry.modelData.caption
                        onOpened: card.imageOpened(url)
                    }
                }
                Component {
                    id: line
                    RowLayout {
                        spacing: theme.space2
                        Text {
                            Layout.alignment: Qt.AlignTop
                            visible: entry.modelData.bullet
                            text: entry.modelData.level > 0 ? "◦" : "•"
                            textFormat: Text.PlainText
                            color: theme.dimText
                            Accessible.ignored: true
                        }
                        NotesText {
                            Layout.fillWidth: true
                            text: entry.modelData.html
                        }
                    }
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: theme.space1
            visible: card.overlays.length > 0
            spacing: theme.space2
            Repeater {
                model: card.overlays
                TpButton {
                    required property string modelData
                    readonly property bool running: backend.enabledOverlays.indexOf(modelData) >= 0
                    readonly property string overlayName: backend.overlayLabel(modelData)
                    size: "sm"
                    accent: !running
                    glyph: running ? "" : ""  // sliders, play
                    text: running ? i18n.trm("Options: " + overlayName) : i18n.trm("Try " + overlayName)
                    tip: running ? i18n.tr("Open the options of this overlay")
                                 : i18n.tr("Turn this overlay on in the loaded preset (Undo in the message shown after)")
                    onClicked: running ? backend.overlayOptions(modelData) : backend.tryOverlay(modelData)
                }
            }
        }
    }
}
