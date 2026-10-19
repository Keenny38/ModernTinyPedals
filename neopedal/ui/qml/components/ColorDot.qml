import QtQuick

// Small round color mark (lap color, class color, legend entry)
Rectangle {
    property real size: Math.round(theme.em * 0.55)
    width: size
    height: size
    radius: size / 2
}
