import QtQuick

// Surface for page sections: rounded, subtle border
Rectangle {
    radius: theme.em * 0.75
    color: theme.base
    border.width: 1
    border.color: theme.dark ? Qt.lighter(theme.base, 1.35) : theme.border
}
