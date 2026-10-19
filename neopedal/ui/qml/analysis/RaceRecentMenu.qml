import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Files of a kind opened or saved last (kind: history, race_plan, tyre_plan), newest first: submenu next to
// an Open action, or menu of its own (first: items declared before the files). Files deleted or moved
// meanwhile left out when it opens.
TpMenu {
    id: menu
    property string kind: ""
    property int first: 0
    readonly property var files: backend.recentFiles[kind] || []
    title: i18n.tr("Open Recent")
    onAboutToShow: backend.refreshRecent()
    Instantiator {
        model: menu.files.length ? menu.files : [{ path: "", name: i18n.tr("No recent files") }]
        delegate: Action {
            required property var modelData
            text: modelData.name
            enabled: modelData.path !== ""
            onTriggered: backend.openRecent(menu.kind, modelData.path)
        }
        onObjectAdded: function(index, object) { menu.insertAction(menu.first + index, object) }
        onObjectRemoved: function(index, object) { menu.removeAction(object) }
    }
}
