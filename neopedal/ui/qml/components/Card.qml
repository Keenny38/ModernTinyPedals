import QtQuick

// Surface for page sections: card surface above the page (theme.surfaceCard), subtle border, card corners
Rectangle {
    radius: theme.radiusLg
    color: theme.surfaceCard
    border.width: 1
    border.color: theme.strokeSubtle
}
