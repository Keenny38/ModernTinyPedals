import QtQuick

// Text in a type role: size, weight, color, spacing & figures from the role (one scale for every page).
// Plain text & cut with "..." by default (texts of values are never markup); any font or color set by the user of
// the component wins over its role.
//   role       size              weight     color    use
//   display    fontDisplay       DemiBold   text     key figure of a page (display face)
//   title      fontHeading       DemiBold   text     page title (display face; the nav rail already names the page)
//   subtitle   fontSubtitle      DemiBold   text     card & section titles
//   body       base              Normal     text     running text (default)
//   label      fontLabel         Normal     text     field & setting labels, list names
//   caption    fontCaption       Normal     dimText  help & detail lines, texts under values
//   overline   fontCaption       DemiBold   dimText  small capitals above a group ("SESSION"), letter spaced
//   numeric    base              Normal     text     numbers & times: tabular figures (aligned columns)
// wrap: long text on several lines (help lines), never cut. tabular: tabular figures for any role (numeric sets it). heading: told to screen readers as a heading
// (display, title, subtitle & overline are). Display face: theme.displayFont (Segoe UI Variable Display), only set
// for display & title (other roles keep the app font and its fallback families).
//   TpText { role: "caption"; text: i18n.tr("Saved with the preset") }
Text {
    id: label
    property string role: "body"
    property bool wrap: false
    property bool tabular: role === "numeric"
    property bool heading: role === "title" || role === "subtitle" || role === "overline" || role === "display"
    readonly property bool displayFace: role === "display" || role === "title"

    textFormat: Text.PlainText  // values of pages are never markup (StyledText only for escaped text)
    elide: wrap ? Text.ElideNone : Text.ElideRight
    wrapMode: wrap ? Text.WordWrap : Text.NoWrap
    color: role === "caption" || role === "overline" ? theme.dimText : theme.text
    font.pointSize: role === "display" ? theme.fontDisplay
                  : role === "title" ? theme.fontHeading
                  : role === "subtitle" ? theme.fontSubtitle
                  : role === "label" ? theme.fontLabel
                  : role === "caption" || role === "overline" ? theme.fontCaption
                  : theme.fontPoint
    font.weight: displayFace || role === "subtitle" || role === "overline" ? Font.DemiBold : Font.Normal
    font.capitalization: role === "overline" ? Font.AllUppercase : Font.MixedCase
    font.letterSpacing: role === "overline" ? theme.letterSpacingOverline : 0
    font.features: tabular ? { "tnum": 1 } : ({})
    Accessible.role: heading ? Accessible.Heading : Accessible.StaticText
    Accessible.name: text

    // Display face written only for display roles: never written, other roles keep the app font families
    Binding { target: label; property: "font.family"; value: theme.displayFont; when: label.displayFace }
    Binding { target: label; property: "font.styleName"; value: theme.displayStyle; when: label.displayFace && theme.displayStyle !== "" }
}
