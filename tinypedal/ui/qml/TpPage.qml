import QtQuick

// Page background with controls palette from app theme (Basic style controls follow it)
Rectangle {
    color: theme.window
    palette.window: theme.window
    palette.base: theme.base
    palette.text: theme.text
    palette.windowText: theme.text
    palette.button: theme.raised
    palette.buttonText: theme.text
    palette.highlight: theme.accent
    palette.highlightedText: "white"
    palette.mid: theme.border
    palette.midlight: theme.hover
    palette.dark: theme.accent
    palette.light: theme.raised
    palette.toolTipBase: theme.raised
    palette.toolTipText: theme.text
}
