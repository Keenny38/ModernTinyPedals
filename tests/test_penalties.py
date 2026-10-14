"""Penalties of game results stream (LMU): kind, time, served, added at finish, disqualified; shown in driver lists"""

from neopedal import penalty_info as pi
from neopedal.adapter.lmu_connector import LMUResults

RECEIVED = (b'<Penalty Driver="Luk Poe" ID="41" Penalty="Stop/Go" Time="10" Laps="0" Reason="Speeding In Pitlane" '
            b'et="1325.3">Luk Poe received Stop/Go penalty, 10s, 0laps for Speeding In Pitlane. Result: penalties=1, '
            b'1st=Stop/Go,10s</Penalty>')
SECOND = (b'<Penalty Driver="Luk Poe" ID="41" Penalty="Drive Thru" Time="0" Laps="0" Reason="Speeding" et="1400.0">'
          b'Luk Poe received Drive Thru penalty, 0s, 0laps for Speeding. Result: penalties=2, 1st=Stop/Go,10s</Penalty>')
SERVED = (b'<Penalty et="1500.0">Luk Poe served 1st Stop/Go penalty, result: penalties=1, 1st=Drive Thru,0s'
          b'</Penalty>')
ADDED = b'<Penalty et="600.2">Luk Poe finished before serving penalty, added 35 seconds to totalET</Penalty>'
DQ = b'<Penalty Driver="Ana D&apos;Arc" ID="8" Penalty="Disqualify" et="986.5">Disqualify</Penalty>'
TIME = (b'<Penalty Driver="Tim" ID="3" Penalty="Time" Time="10" Laps="0" Reason="Track Limits" et="70.0">Tim received '
        b'Time penalty, 10s, 0laps for Track Limits. Result: penalties=1, 1st=Time,10s</Penalty>')


def follow(*lines: bytes) -> pi.Penalty:
    state = pi.NO_PENALTY
    for line in lines:
        parsed = pi.parse_line(line)
        assert parsed is not None
        state = pi.apply_line(state, *parsed[1:])
    return state


def test_penalty_lines():
    assert pi.parse_line(b"<Incident et='1'>x</Incident>") is None
    assert pi.parse_line(RECEIVED)[0] == b"Luk Poe" and pi.parse_line(SERVED)[0] == b"Luk Poe"
    assert pi.parse_line(DQ)[0] == b"Ana D'Arc"  # XML entities decoded as shared memory names
    assert follow(RECEIVED) == pi.Penalty(1, "Stop/Go", 10)
    assert follow(RECEIVED, SECOND) == pi.Penalty(2, "Stop/Go", 10)
    assert follow(RECEIVED, SECOND, SERVED) == pi.Penalty(1, "Drive Thru", 0)
    assert follow(RECEIVED, ADDED) == pi.Penalty(0, "", 0, 35)
    assert follow(DQ).disqualified


def test_penalty_labels():
    assert pi.label(follow(RECEIVED)) == "SG10" and pi.short_label(follow(RECEIVED)) == "SG"
    assert pi.label(follow(RECEIVED, SECOND)) == "SG\u00d72"
    assert pi.label(follow(RECEIVED, SECOND, SERVED)) == "DT"
    assert pi.label(follow(TIME)) == "+10s" and pi.short_label(follow(TIME)) == "TP"
    assert pi.label(follow(RECEIVED, ADDED)) == "+35s" and pi.short_label(follow(RECEIVED, ADDED)) == ""
    assert pi.label(follow(DQ)) == "DQ" and pi.short_label(follow(DQ)) == "DQ"
    assert pi.label(pi.NO_PENALTY, 1) == "PEN" and pi.label(pi.NO_PENALTY, 2) == "PEN\u00d72"  # kind unknown
    assert pi.label(pi.NO_PENALTY) == "" and pi.short_label(pi.NO_PENALTY, 1) == "PN"
    assert pi.count_text(2, pi.NO_PENALTY) == "2" and pi.count_text(-1, follow(RECEIVED)) == "SG"
    assert pi.kind_code("Disqualify Now") == "DN"


def test_live_stream_penalties_of_each_driver():
    results = LMUResults()
    results.update(RECEIVED + b"\n" + DQ)
    results.update(SECOND)
    assert results.penalty(b"Luk Poe") == pi.Penalty(2, "Stop/Go", 10)
    assert results.penalty(b"Ana D'Arc").disqualified
    assert results.penalty(b"Nobody") is pi.NO_PENALTY
    results.update(SERVED)
    assert results.penalty(b"Luk Poe").kind == "Drive Thru"
    assert results.get(b"Luk Poe") is LMUResults.DEFAULT  # penalties not counted as incidents


def test_pit_stops_cell_shows_penalty(ui_env, bundled_fonts):
    from neopedal.setting import cfg
    from neopedal.widget._modern.table import BADGE
    from tests.test_modern_table_rows import new_table

    widget = new_table(cfg, "standings")
    style, theme = widget.row_style, widget.theme
    cell = style.pitstop_cell(-1, False, follow(RECEIVED))
    assert cell.kind == BADGE and cell.text == "SG10" and cell.fill == theme.negative  # red as app pages
    assert style.pitstop_cell(-1, False).text == "PEN"  # kind unknown: given before app started
    assert style.pitstop_cell(2, False, follow(DQ)).fill == theme.negative
    assert style.pitstop_cell(2, False, follow(RECEIVED, ADDED)).text == "+35s"
    assert style.pitstop_cell(2, False).text == "2"
    widget.deleteLater()
