import QtQuick
import QtQuick.Controls.Basic

// Busy spinner: turns only while shown on a page on screen (pageState). size "sm" (inline: headers, rows,
// toolbars), "md" (compact waiting state) or "lg" (panel waiting state). A panel without content to show uses
// TpStateView { loading } instead (spinner & text centered).
//   TpSpinner { visible: backend.saving; Layout.alignment: Qt.AlignVCenter }
BusyIndicator {
    property string size: "sm"

    running: visible && pageState.active
    implicitWidth: Math.round(size === "lg" ? theme.iconHero : size === "md" ? theme.iconLg : theme.em * 1.3)
    implicitHeight: implicitWidth
    Accessible.role: Accessible.Animation
    Accessible.name: i18n.tr("Busy")
}
