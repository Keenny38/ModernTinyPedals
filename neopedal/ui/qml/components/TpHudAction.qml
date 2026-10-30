import QtQuick
import QtQuick.Controls.Basic

// Game HUD part in a HUD menu (TpMenu): checked while the game shows it, disabled when the game has no such part.
// hudState: HUD part key -> shown (true / false) from the game, a missing key: not available. A click asks the page
// (toggleRequested) and the check follows the game again (also when the game refused the change).
//   TpHudAction { key: "chat"; text: i18n.tr("Chat"); hudState: backend.camera.hudState
//                 onToggleRequested: function(key) { backend.camera.toggleHudComponent(key) } }
Action {
    id: hudAction
    property string key: ""
    property var hudState: ({})
    signal toggleRequested(string key)

    objectName: "hud_" + key
    checkable: true
    enabled: !!hudState && hudState[key] !== undefined
    checked: !!hudState && hudState[key] === true
    onTriggered: {
        hudAction.toggleRequested(hudAction.key)
        // click toggled checked by itself: state of game shown again (also when the toggle was refused)
        checked = Qt.binding(function() { return !!hudAction.hudState && hudAction.hudState[hudAction.key] === true })
    }
}
