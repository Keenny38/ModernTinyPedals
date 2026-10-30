import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "../components"

// Track selector shown as page title: selected track, popup with search field (part of name) & tracks with
// last driven date, All Tracks first. Up / Down move in list, Enter selects, Escape closes; openSearch() opens it.
// Optional: busy (tracks listed in background: spinner while list empty), emptyText (no track matching search).
// Source of tracks: page backend by default (tracks entries {key, label, logo, date, current}, currentTrack,
// currentLabel, currentLogo, allTracks, selectTrack(key)), or given by the page (lap viewer: trackModel, currentKey,
// currentLabel, currentLogo, selectTrack). Tab reaches it (Space / Enter / Down open it), a click leaves keys where
// they were.
// Rows: trackModel of page backend (rows with the same roles, filtered there: setSearch, indexOf, keyAt), else tracks
// filtered here into a list model. Either way only rows leaving or coming back change while typing: delegates of
// kept rows stay (no list rebuilt per key).
AbstractButton {
    id: picker

    property string filter: ""  // search text applied (typing settled)
    property bool busy: false
    property string emptyText: i18n.tr("No track found")
    property var tracks: backend.tracks  // without trackModel
    property QtObject trackModel: null
    property string currentKey: backend.currentTrack
    property string currentLabel: backend.currentLabel
    property string currentLogo: backend.currentLogo
    property bool allTracks: backend.allTracks
    property var selectTrack: function(key) { backend.selectTrack(key) }
    signal opened()  // popup opened: page may list tracks again
    signal closed()  // popup closed: page may give keyboard focus back to its list
    readonly property string current: currentKey  // read once for every row

    onFilterChanged: applyRows()
    onTracksChanged: if (!trackModel) applyRows()
    onTrackModelChanged: applyRows()
    Component.onCompleted: applyRows()
    // Rows shown: tracks whose name holds the search text (any case), in tracks order
    function applyRows() {
        if (trackModel) {
            trackModel.setSearch(filter)
            return
        }
        var words = filter.toLowerCase().trim()
        var tracks = picker.tracks || []  // read once: each read converts the whole list
        var rows = []
        for (var i = 0; i < tracks.length; i++) {
            var entry = tracks[i]
            if (words === "" || entry.label.toLowerCase().indexOf(words) >= 0)
                rows.push({"key": entry.key, "label": entry.label, "logo": entry.logo || "", "date": entry.date || "",
                           "current": entry.current === true})  // every role set (list model roles fixed by first row)
        }
        syncRows(rows)
    }
    // List model rows become rows (matched by key): rows not wanted removed (runs together), new ones inserted, kept
    // ones moved if tracks order changed & updated if changed. Each model row read about once (search: O(rows))
    function syncRows(rows) {
        var wanted = {}
        for (var i = 0; i < rows.length; i++) wanted[rows[i].key] = true
        var end = localRows.count
        for (var n = localRows.count - 1; n >= -1; n--) {
            if (n >= 0 && wanted[localRows.get(n).key] === true) {
                if (n + 1 < end) localRows.remove(n + 1, end - n - 1)
                end = n
            } else if (n < 0 && end > 0) {
                localRows.remove(0, end)
            }
        }
        var kept = {}  // keys of rows left (all wanted)
        for (var k = 0; k < localRows.count; k++) kept[localRows.get(k).key] = true
        for (var r = 0; r < rows.length; r++) {
            var row = rows[r]
            var at = r
            if (kept[row.key] === true)  // further down if tracks order changed
                while (at < localRows.count && localRows.get(at).key !== row.key) at++
            if (kept[row.key] !== true || at >= localRows.count) {  // new row (or key listed twice)
                localRows.insert(r, row)
                continue
            }
            if (at !== r) localRows.move(at, r, 1)
            var shown = localRows.get(r)
            if (shown.label !== row.label || shown.logo !== row.logo || shown.date !== row.date || shown.current !== row.current)
                localRows.set(r, row)
        }
        if (localRows.count > rows.length) localRows.remove(rows.length, localRows.count - rows.length)
    }
    function rowOf(key) {
        if (trackModel) return trackModel.indexOf(key)
        for (var i = 0; i < localRows.count; i++) if (localRows.get(i).key === key) return i
        return -1
    }
    function keyAt(index) {  // undefined if no such row ("" is a key: All Tracks)
        if (trackModel) return trackModel.keyAt(index)
        return index >= 0 && index < localRows.count ? localRows.get(index).key : undefined
    }
    ListModel { id: localRows }

    function applyFilter() {
        if (filter !== search.text) {
            filter = search.text
            list.currentIndex = 0
        }
    }
    function choose(key) {
        popup.close()
        if (key !== undefined && key !== null) picker.selectTrack(key)
    }
    function openSearch() {
        if (!popup.visible) popup.open()
    }

    implicitHeight: Math.round(theme.em * 2.6)
    implicitWidth: contentItem.implicitWidth
    hoverEnabled: true
    focusPolicy: Qt.TabFocus  // Tab reaches it, a click leaves keyboard focus where it was (charts keep arrows)
    onClicked: popup.visible ? popup.close() : popup.open()
    Keys.onDownPressed: openSearch()
    Keys.onReturnPressed: openSearch()
    Keys.onEnterPressed: openSearch()
    Accessible.role: Accessible.ComboBox
    Accessible.name: i18n.tr("Track") + ": " + picker.currentLabel

    background: Rectangle {
        radius: theme.radiusLg
        color: picker.down || popup.visible ? theme.hover
             : picker.hovered ? theme.surfaceHover : "transparent"
        border.width: popup.visible ? 1 : 0
        border.color: theme.accent
        Behavior on color { ColorAnimation { duration: theme.motionFast } }
        FocusRing { visible: picker.visualFocus }
    }
    contentItem: RowLayout {
        spacing: theme.space3
        Icon {  // globe (All Tracks), map pin
            glyph: picker.allTracks ? "" : ""
            color: theme.accent
            size: theme.iconMd
            Layout.leftMargin: theme.space3
            visible: iconShown && !logoItem.shown  // circuit logo of game shown instead
        }
        GameLogo {  // circuit logo of game
            id: logoItem
            source: picker.currentLogo
            boxWidth: theme.em * 3.2
            boxHeight: theme.em * 1.9
            Layout.leftMargin: theme.space3
        }
        Text {
            text: picker.currentLabel
            textFormat: Text.PlainText
            color: theme.text
            font.pointSize: theme.fontLarge
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            Layout.fillWidth: true
            Layout.maximumWidth: implicitWidth
        }
        Icon {
            glyph: ""  // chevron down
            fallback: "▾"
            size: theme.iconSm
            color: picker.hovered || popup.visible ? theme.text : theme.dimText
            rotation: popup.visible && iconShown ? 180 : 0
            Layout.rightMargin: theme.space3
            Behavior on rotation { NumberAnimation { duration: theme.motionBase } }
        }
    }

    TpPopup {
        id: popup
        y: picker.height + theme.space1
        width: Math.max(picker.width, theme.em * 24)
        padding: theme.space2
        focus: true
        onOpened: {
            search.clearSearch()
            picker.filter = ""
            list.currentIndex = Math.max(0, picker.rowOf(picker.current))
            search.forceActiveFocus()
            picker.opened()
        }
        onClosed: picker.closed()
        contentItem: ColumnLayout {
            spacing: theme.space1
            TpSearchField {
                id: search
                Layout.fillWidth: true
                implicitHeight: Math.round(theme.fieldHeight)
                searchDelay: 120  // list filtered once typing settles
                placeholderText: i18n.tr("Search track…")
                onSearchChanged: picker.applyFilter()
                Keys.onDownPressed: {
                    picker.applyFilter()
                    list.currentIndex = Math.min(list.currentIndex + 1, list.count - 1)
                }
                Keys.onUpPressed: {
                    picker.applyFilter()
                    list.currentIndex = Math.max(list.currentIndex - 1, 0)
                }
                Keys.onReturnPressed: {
                    picker.applyFilter()
                    picker.choose(picker.keyAt(list.currentIndex))
                }
                Keys.onEnterPressed: {
                    picker.applyFilter()
                    picker.choose(picker.keyAt(list.currentIndex))
                }
                Keys.onEscapePressed: popup.close()
            }
            ListView {
                id: list
                Layout.fillWidth: true
                implicitHeight: Math.min(contentHeight, theme.em * 24)
                clip: true
                model: picker.trackModel || localRows
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar {}
                delegate: ItemDelegate {
                    id: entryItem
                    required property string key
                    required property string label
                    required property string logo
                    required property string date
                    required property bool current
                    required property int index
                    width: ListView.view.width
                    height: Math.round(theme.rowCompact)
                    verticalPadding: 0  // style padding (12) is taller than the row: content pushed down
                    highlighted: ListView.isCurrentItem || hovered
                    Accessible.name: entryItem.label
                    onClicked: picker.choose(entryItem.key)
                    contentItem: RowLayout {
                        spacing: theme.space3
                        Item {  // circuit logo of game, same room on every row
                            implicitWidth: theme.em * 2.4
                            implicitHeight: theme.em * 1.3
                            GameLogo {
                                anchors.centerIn: parent
                                source: entryItem.logo
                                boxWidth: theme.em * 2.4
                                boxHeight: theme.em * 1.3
                            }
                        }
                        Text {
                            text: entryItem.label
                            textFormat: Text.PlainText
                            color: theme.text
                            font.weight: entryItem.key === picker.current ? Font.DemiBold : Font.Normal
                            font.italic: entryItem.key === ""
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Icon {
                            visible: entryItem.current
                            fallback: "⚑"
                            glyph: ""  // flag: track of running session
                            size: theme.iconSm
                            color: theme.accent
                        }
                        Text {
                            text: entryItem.date === "-" ? "" : entryItem.date
                            textFormat: Text.PlainText
                            color: theme.dimText
                            font.pointSize: theme.fontSmall
                            font.features: { "tnum": 1 }
                        }
                    }
                    background: TpListRow {
                        hovered: entryItem.hovered
                        selected: entryItem.ListView.isCurrentItem
                    }
                }
            }
            Text {
                visible: list.count === 0 && !picker.busy
                text: picker.emptyText
                textFormat: Text.PlainText
                color: theme.dimText
                Layout.margins: theme.space3
            }
            Item {  // tracks listed in background
                visible: list.count === 0 && picker.busy
                Layout.fillWidth: true
                implicitHeight: busyState.implicitHeight + theme.space5
                TpLoadingState { id: busyState; anchors.centerIn: parent }
            }
        }
    }
}
