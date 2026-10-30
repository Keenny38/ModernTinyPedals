"""Driver & Safety Rank of other drivers of an online session: RaceControl profiles by name, overlay columns,
field level of Session overlay, Broadcast Director cards"""

import json

import pytest

from neopedal.process import driver_ranks as dr
from neopedal.process import field_ranks as fr
from neopedal.process import raceos

NOW = 1_792_247_000.0  # 2026-10-17 14:23:20 UTC


def iso(stamp: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def profile(name: str, driver=("Silver", 2, 40), safety=("Gold", 1, 10), badge="sr-clean") -> dict:
    """RaceControl player as POST api/v1/players gives it (checked live)"""
    return {"id": name, "name": name, "username": name, "platforms": [{"id": "7656", "platform": "steam"}],
            "driverRank": {"elo": 0, "rank": driver[0], "tier": driver[1], "progress": driver[2]},
            "safetyRank": {"rank": safety[0], "tier": safety[1], "rating": 0, "progress": safety[2]},
            "profile": {"nationality": "FR", "badge": badge}}


PROFILES = {
    "Henrik Rasmussen": profile("Henrik Rasmussen", ("Silver", 1, 90), ("Platinum", 2, 30), "sr-saint"),
    "Austin Martin": profile("Austin Martin", ("Bronze", 3, 30)),
    "Nick Cloat": profile("Nick Cloat", ("Bronze", 3, 0), ("Silver", 1, 30)),
    "Keenny Hess": profile("Keenny Hess", ("Silver", 2, 36), ("Bronze", 0, 0)),
}


class FakeSource:
    def __init__(self):
        self.on = True
        self.server = True
        self.online = True
        self.requests: list[list[str]] = []

    def enabled(self):
        return self.on

    def joined(self):
        return self.server

    def post(self, path, payload):
        assert path == fr.PLAYERS_PATH
        self.requests.append(payload["usernames"])
        if not self.online:
            return None
        return [PROFILES[name] for name in payload["usernames"] if name in PROFILES]


def make_field():
    clock = [0.0]
    source = FakeSource()
    field = fr.FieldRanks(source, clock=lambda: clock[0], run=lambda work: work())
    return field, source, clock


SESSION = ["Henrik Rasmussen", "Austin Martin#9566", "Nick Cloat", "Keenny Hess"]


def test_driver_key_and_levels():
    assert fr.driver_key("Austin  Martin#9566") == "austin martin" == fr.driver_key("austin martin")
    assert fr.strip_suffix("Austin Martin#9566") == "Austin Martin"
    assert fr.rank_of_level(dr.Rank("Silver", 2, 40).level) == dr.Rank("Silver", 2, 40)
    assert fr.rank_of_level(dr.Rank("Platinum", 3, 100).level) == dr.Rank("Platinum", 3, 99)
    assert fr.rank_of_level(-1) is None
    level = fr.average_level([dr.DriverRanks("a", "", "", "", dr.Rank("Silver", 1, 0), None),
                              dr.DriverRanks("b", "", "", "", dr.Rank("Gold", 1, 0), dr.Rank("Bronze", 3, 50))])
    assert level == fr.FieldLevel(dr.Rank("Silver", 2, 50), dr.Rank("Bronze", 3, 50), 2)


def test_drivers_of_session_asked_by_name():
    field, source, _ = make_field()
    field.poll(SESSION)
    assert source.requests == [["Henrik Rasmussen", "Austin Martin", "Nick Cloat", "Keenny Hess"]]  # no suffix
    assert field.ranks_of("Austin Martin#9566").driver == dr.Rank("Bronze", 3, 30)
    assert field.ranks_of("henrik rasmussen").badge == "sr-saint"
    assert field.ranks_of("Unknown") is None and field.serial == 1
    level = field.level([*SESSION, "Unknown"])
    assert level.known == 4 and level.driver[:2] == ("Silver", 1)


def test_drivers_joining_asked_at_once_leavers_kept():
    field, source, clock = make_field()
    field.poll(SESSION)
    PROFILES["Late Driver"] = profile("Late Driver", ("Gold", 3, 0))
    try:
        clock[0] = fr.JOIN_SECONDS  # joins before next check: asked at once, alone
        field.poll([*SESSION, "Late Driver"])
        assert source.requests[-1] == ["Late Driver"] and field.ranks_of("Late Driver") is not None
        clock[0] = fr.JOIN_SECONDS + 0.5  # another one right after: grouped, asked once JOIN_SECONDS passed
        field.poll([*SESSION, "Late Driver", "Austin Martin#1"])
        field.poll([*SESSION, "Late Driver", "Austin Martin#1", "Ghost"])
        assert len(source.requests) == 2
        clock[0] = fr.JOIN_SECONDS * 2
        field.poll([*SESSION, "Late Driver", "Austin Martin#1", "Ghost"])
        assert source.requests[-1] == ["Ghost"]  # Austin Martin known (same driver, other suffix)
    finally:
        del PROFILES["Late Driver"]
    clock[0] = fr.JOIN_SECONDS * 3  # Late Driver leaves: not in field level any more, ranks kept if back
    assert field.level(SESSION).known == 4
    field.poll(SESSION)
    field.poll([*SESSION, "Late Driver"])
    assert field.ranks_of("Late Driver").driver == dr.Rank("Gold", 3, 0) and len(source.requests) == 3
    clock[0] = fr.KEEP_SECONDS  # known drivers read again (ranks change after races)
    field.poll(SESSION)
    assert sorted(source.requests[-1]) == sorted(["Henrik Rasmussen", "Austin Martin", "Nick Cloat", "Keenny Hess"])


def test_driver_without_profile_or_failed_read_asked_again_later():
    field, source, clock = make_field()
    source.online = False
    field.poll(["Ghost Driver", "Nick Cloat"])
    assert field.ranks_of("Nick Cloat") is None
    clock[0] = fr.CHECK_SECONDS
    field.poll(["Ghost Driver", "Nick Cloat"])
    assert len(source.requests) == 1  # failed read: not asked again every check
    source.online = True
    clock[0] = fr.MISSING_SECONDS
    field.poll(["Ghost Driver", "Nick Cloat"])
    assert len(source.requests) == 2 and field.ranks_of("Nick Cloat") is not None
    clock[0] = fr.MISSING_SECONDS * 2
    field.poll(["Ghost Driver", "Nick Cloat"])
    assert "Ghost Driver" in source.requests[-1]  # no profile: asked again
    assert field.ranks_of("Nick Cloat") is not None  # known one kept


def test_every_driver_read_again_after_session_end():
    field, source, clock = make_field()
    field.poll(SESSION)
    clock[0] = 10.0
    field.session_ended()
    clock[0] = 10.0 + fr.RESULTS_DELAYS[0] - 1
    field.poll(SESSION)
    assert len(source.requests) == 1
    PROFILES["Nick Cloat"] = profile("Nick Cloat", ("Silver", 1, 5))  # ranks after race
    try:
        clock[0] = 10.0 + fr.RESULTS_DELAYS[0]  # before next check: read at once
        field.poll(SESSION)
        assert len(source.requests[-1]) == 4 and field.ranks_of("Nick Cloat").driver == dr.Rank("Silver", 1, 5)
        for delay in fr.RESULTS_DELAYS[1:]:
            clock[0] = 10.0 + delay
            field.poll(SESSION)
        assert len(source.requests) == 1 + len(fr.RESULTS_DELAYS)
    finally:
        PROFILES["Nick Cloat"] = profile("Nick Cloat", ("Bronze", 3, 0), ("Silver", 1, 30))


def test_many_drivers_asked_in_batches():
    field, source, _ = make_field()
    names = [f"Driver {index}" for index in range(fr.BATCH + 5)]
    field.poll(names)
    assert [len(batch) for batch in source.requests] == [fr.BATCH, 5]


def test_cleared_when_leaving_server_or_option_off():
    field, source, clock = make_field()
    field.poll(SESSION)
    source.server = False
    clock[0] = fr.CHECK_SECONDS
    field.poll(SESSION)
    assert field.ranks_of("Nick Cloat") is None and field.serial == 2
    source.server = True
    clock[0] = fr.CHECK_SECONDS * 2
    field.poll(SESSION)
    assert field.ranks_of("Nick Cloat") is not None  # joined again: asked at once
    source.on = False
    requests = len(source.requests)
    field.poll(SESSION)  # option off: cleared at once, nothing read
    assert field.ranks_of("Nick Cloat") is None and len(source.requests) == requests


def test_offline_session_never_asks():
    field, source, _ = make_field()
    source.server = False
    field.poll(SESSION)
    assert source.requests == []


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.answers = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append((method, url, headers))
        status, data = self.answers.pop(0) if self.answers else (0, None)
        return status, json.dumps(data).encode() if data is not None else b""


def test_client_token_kept_for_other_reads():
    http = FakeHttp()
    wall = [NOW]
    clock = [0.0]
    client = raceos.RaceOSClient(lambda: "ticket", http=http, clock=lambda: clock[0], wall_clock=lambda: wall[0])
    auth = {"accessToken": "tok", "expiresAt": iso(NOW + 1800), "player": None}
    http.answers = [(200, auth), (200, [1]), (200, [2])]
    assert client.get("api/v1/daily/list/beginner?take=2") == [1]
    assert client.get("api/v1/x") == [2]  # same token
    assert [call[0] for call in http.calls] == ["POST", "GET", "GET"]
    assert http.calls[1][2]["Game-Authorization"] == "Bearer tok"
    assert http.calls[1][1] == f"{raceos.RACEOS_URL}/api/v1/daily/list/beginner?take=2"
    wall[0] = NOW + 1800 - raceos.TOKEN_MARGIN  # about to expire: signed in again
    http.answers = [(200, auth), (401, None)]
    assert client.get("api/v1/x") is None
    assert client.get("api/v1/x") is None and len(http.calls) == 5  # new token refused: waits before signing in
    clock[0] += raceos.RETRY_SECONDS
    http.answers = [(200, auth), (200, [3])]  # refused token dropped: signed in again
    assert client.get("api/v1/x") == [3]
    assert [call[0] for call in http.calls] == ["POST", "GET", "GET", "POST", "GET", "POST", "GET"]
    http.answers = [(200, auth), (200, [4])]  # token about to expire: signed in first
    assert client.post("api/v1/players", {"usernames": ["A"]}) == [4]
    method, url, headers = http.calls[-1]
    assert (method, url, headers["Content-Type"]) == ("POST", f"{raceos.RACEOS_URL}/api/v1/players",
                                                      "application/json")


def test_client_no_token_no_read():
    http = FakeHttp()
    client = raceos.RaceOSClient(lambda: "", http=http)
    assert client.get("api/v1/x") is None and http.calls == []


@pytest.fixture
def known_field(monkeypatch):
    """Field ranks of sample cars (overlay pictures) known, nothing read"""
    from neopedal import rank_info

    monkeypatch.setattr(rank_info.ranks, "poll", lambda: None)
    monkeypatch.setattr(rank_info.ranks, "drivers", [])
    monkeypatch.setattr(rank_info.field, "poll", lambda names: None)
    ranks: dict = {}
    monkeypatch.setattr(rank_info.field, "_ranks", ranks)
    return ranks


@pytest.mark.parametrize("name", ["standings", "relative"])  # player row shown
def test_driver_ranks_and_badge_columns(ui_env, bundled_fonts, known_field, name, monkeypatch, tmp_path):
    """Driver & safety ranks and game badge: two columns, each shown & moved on its own"""
    from neopedal.setting import cfg
    from neopedal.userfile.badge_icons import icons
    from neopedal.widget._modern.rows import DASH
    from neopedal.widget._modern.table import EMPTY_CELL, ICON, PAIR, TEXT
    from tests.test_modern_table_rows import new_table, sample
    from tests.test_standings_gaps_columns import column_cells

    setting = cfg.user.setting[name]
    setting["column_driver_ranks"] = True
    setting["column_driver_badge"] = True
    widget = new_table(cfg, name)
    cars, context = sample(widget)
    player = cars.vehicles[cars.player_index].driverName  # shown by both widgets
    known_field[fr.driver_key(player)] = dr.DriverRanks(player, "", "", "", dr.Rank("Gold", 2, 0),
                                                        dr.Rank("Platinum", 1, 0), "sr-saint")
    monkeypatch.setattr(icons, "request", lambda key: None)  # no icon download
    monkeypatch.setattr(cfg.path, "game_image", str(tmp_path))
    widget.show_field(cars, context)
    cells = column_cells(widget, "driver_ranks")
    assert all(cell.kind == PAIR and cell.extra[0].kind == TEXT for cell in cells)  # ranks only, no badge
    texts = {(cell.extra[0].text, cell.extra[1].text) for cell in cells}
    assert ("G2", "P1") in texts and (DASH, DASH) in texts  # unknown drivers: dashes
    gold = next(cell for cell in cells if cell.extra[0].text == "G2")
    assert gold.extra[0].color.name().upper() == dr.RANK_COLORS["gold"].upper()
    badges = column_cells(widget, "driver_badge")
    assert len(badges) == len(cells) and EMPTY_CELL in badges  # unknown drivers: no badge
    badge = next(cell for cell in badges if cell != EMPTY_CELL)
    assert badge.kind == ICON and badge.text == "" and badge.color.name().upper() == "#1EFF6B"  # dot: no icon yet
    widget.grab()  # dot drawn
    icon = tmp_path / "badge" / "sr-saint.svg"
    icon.parent.mkdir()
    icon.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8" '
                    'fill="#0f0"/></svg>', encoding="utf-8")
    monkeypatch.setattr(icons, "version", icons.version + 1)  # icon saved
    widget.show_field(cars, context)
    badge = next(cell for cell in column_cells(widget, "driver_badge") if cell != EMPTY_CELL)
    assert badge.text == str(icon)
    widget.grab()  # icon drawn
    widget.deleteLater()
    setting["column_driver_ranks"] = False  # badge alone: ranks still read
    alone = new_table(cfg, name)
    assert [column.key for column in alone.table.columns if column.key.startswith("driver_")][-1:] == ["driver_badge"]
    assert "driver_ranks" not in {column.key for column in alone.table.columns}
    alone.show_field(cars, context)
    assert any(cell.kind == ICON for cell in column_cells(alone, "driver_badge"))
    alone.deleteLater()
    setting["column_driver_badge"] = False


def test_session_field_level(ui_env, bundled_fonts, known_field, monkeypatch):
    from neopedal import rank_info
    from neopedal.module_info import minfo
    from neopedal.setting import cfg
    from neopedal.widget._modern.base import DASH
    from neopedal.widget._modern.session import Realtime
    from tests.test_modern_table_rows import new_table

    cfg.user.setting["session"]["show_field_level"] = True
    widget = new_table(cfg, "session")
    assert isinstance(widget, Realtime) and "field_level" in widget.keys
    assert widget.field_level_value().text == f"{DASH} · {DASH}"  # placeholders
    names = [car.driverName for car in minfo.vehicles.dataSet[:2]]
    for name, rank in zip(names, ("Silver", "Gold")):
        known_field[fr.driver_key(name)] = dr.DriverRanks(name, "", "", "", dr.Rank(rank, 1, 0),
                                                          dr.Rank("Bronze", 2, 0))
    if len(set(names)) == 2 and all(names):
        assert widget.field_level_value().text == "S2 · B2"
    monkeypatch.setattr(rank_info, "field_level", lambda names: fr.FieldLevel(None, dr.Rank("Gold", 1, 0), 3))
    assert widget.field_level_value().text == f"{DASH} · G1"
    widget.deleteLater()
    cfg.user.setting["session"]["show_field_level"] = False


def test_director_card_uses_field_ranks(known_field):
    from neopedal import rank_info

    known_field["driver 3"] = dr.DriverRanks("Driver 3", "", "", "", dr.Rank("Silver", 3, 0), dr.Rank("Gold", 2, 0))
    found = rank_info.driver_ranks("Driver 3#1234")
    assert found.driver.short == "S3" and found.safety.short == "G2"
    from neopedal.ui.quick.director_graphics import badge_name

    assert badge_name("sr-saint") == "Trusted Racer" and badge_name("") == "" and badge_name("unknown") == ""
    assert rank_info.driver_ranks("Nobody") is None


def test_standings_class_sof(ui_env, bundled_fonts, known_field):
    from neopedal import rank_info
    from neopedal.setting import cfg
    from neopedal.widget._modern.table import ClassHeader
    from tests.test_modern_table_rows import new_table, sample

    setting = cfg.user.setting["standings"]
    setting["enable_multi_class_split_mode"] = True
    setting["show_class_header"] = True
    setting["show_class_sof"] = True
    widget = new_table(cfg, "standings")
    cars, context = sample(widget)
    gt3 = [car for car in cars.vehicles if "GT3" in car.vehicleClass]
    for car, rank in zip(gt3[:2], ("Silver", "Gold")):
        known_field[fr.driver_key(car.driverName)] = dr.DriverRanks(car.driverName, "", "", "", dr.Rank(rank, 1, 0),
                                                                    dr.Rank("Platinum", 1, 0))
    from neopedal.widget._modern.sample_field import sample_standings

    widget.show_field(cars, context)  # sample ranks (overlay pictures)
    assert any(row.info for row in widget.state if isinstance(row, ClassHeader))
    widget.demo = False  # ranks of session
    widget.show_rows(cars.vehicles, sample_standings(cars, widget.wcfg), context)
    headers = {row.text: row for row in widget.state if isinstance(row, ClassHeader)}
    gt3_header = next(header for text, header in headers.items() if "GT3" in text)
    assert gt3_header.info == "SoF S2 50% · P1 0%"  # average of known drivers of class
    assert gt3_header.info_color.name().upper() == dr.RANK_COLORS["silver"].upper()
    assert all(not header.info for text, header in headers.items() if "GT3" not in text)  # unknown: nothing
    widget.grab()
    assert rank_info.field_level([gt3[0].driverName, gt3[0].driverName + "#12"]).known == 1  # same driver once
    widget.deleteLater()
    setting["show_class_sof"] = False
