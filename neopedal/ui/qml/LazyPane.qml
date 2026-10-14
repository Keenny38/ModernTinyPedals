import QtQuick

// Content made only once shown (popups & panels of a page are not all made when the page opens): kept made
// afterwards when keep is true (state & scroll kept, opens at once next time), else freed once hidden.
// Popup content: contentItem: LazyPane { shown: popup.visible; sourceComponent: ColumnLayout { ... } }
Loader {
    property bool shown: false
    property bool keep: true
    property bool made: false
    active: shown || (keep && made)
    onLoaded: made = true
}
