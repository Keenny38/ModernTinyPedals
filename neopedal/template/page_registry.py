#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Page registry: every main window page & tool page declared once

Main window pages (navigation rail) and tool pages (Tools page cards, menu, command palette,
navigation rail, home quick access) are read from PAGES. Tables of ui.tools_view, ui.nav_rail,
ui.app & the default rail of setting_global are derived from it. Plain data only (no Qt import):
dialog classes are named by path, imported when first opened.
"""

from __future__ import annotations

from dataclasses import dataclass

PAGE_MAIN = "Pages"  # category of main window pages
# Tool categories: Tools page sections & menu, in order
TOOL_CATEGORIES = ("Utilities", "Editors", "Management", "Advanced")


@dataclass(frozen=True)
class PageSpec:
    """Main window page or tool page

    Args:
        name: Page key (rail & quick access setting), tool dialog module name for tool pages.
        label: Full name (English, translated by tr), rail tooltip.
        glyph: Icon glyph in Segoe Fluent Icons / MDL2 Assets.
        category: PAGE_MAIN, or tool section (see TOOL_CATEGORIES).
        dialog: Tool dialog "module.DialogClass" path relative to ui package ("" for main pages).
        short_label: Rail label (rail buttons are narrow), label if empty.
        letter: Icon drawn without icon font, first letter of short label if empty.
        rail: Position in default navigation rail, -1 if not in it.
        keywords: Extra words finding the tool in command palette (former names, what it covers), both languages.
        status: "module:function" giving status of tool page with an on / off switch ("on", "off", "" closed).
        description: What the page is for, one short sentence (Tools page, command palette).
        listed: Shown on Tools page & Tools menu (Settings: own menu, rail gear & Ctrl+, only).
        wiki: User guide page (and #anchor) explaining the page, opened by the help button.
    """

    name: str
    label: str
    glyph: str
    category: str
    dialog: str = ""
    short_label: str = ""
    letter: str = ""
    rail: int = -1
    keywords: str = ""
    status: str = ""
    description: str = ""
    listed: bool = True
    wiki: str = ""

    @property
    def rail_label(self) -> str:
        return self.short_label or self.label

    @property
    def rail_letter(self) -> str:
        return self.letter or self.rail_label[:1]


# Every page: main window pages first (in tab order), then tools by category (in card order)
PAGES: tuple[PageSpec, ...] = (
    PageSpec("home", "Home", "", PAGE_MAIN, letter="A", rail=0,
             description="Game, preset, overlays & last session at a glance", wiki="Getting-Started#home-page"),  # home
    PageSpec("widget", "Overlays", "", PAGE_MAIN, letter="W", rail=1,
             description="Turn overlays on or off and open their options", wiki="Overlays"),  # all apps grid
    PageSpec("module", "Module", "", PAGE_MAIN, short_label="Modules", letter="M",
             description="Data modules recording what overlays and tools need", wiki="Getting-Started#data-modules"),  # diagnostic
    PageSpec("preset", "Preset", "", PAGE_MAIN, short_label="Presets", letter="P", rail=8,
             description="Load, create, share and restore presets", wiki="Presets-and-Settings#presets"),  # library
    PageSpec("spectate", "Spectate", "", PAGE_MAIN, letter="S",
             description="Choose the driver overlays show while spectating", wiki="Getting-Started#spectate"),  # view
    PageSpec("pacenotes", "Pacenotes", "", PAGE_MAIN, letter="N",
             description="Pace notes played while driving", wiki="Presets-and-Settings#global-config"),  # quick note
    PageSpec("hotkey", "Hotkey", "", PAGE_MAIN, short_label="Hotkeys", letter="H",
             description="Keyboard, wheel and controller shortcuts", wiki="Getting-Started#hotkeys"),  # keyboard
    PageSpec("tools", "Tools", "", PAGE_MAIN, letter="T",
             description="Every tool and editor", wiki="Home#wiki-pages"),  # developer tools
    # Utilities
    PageSpec(
        "race_calculator", "Race Calculator", "", "Utilities",  # calculator
        "race_calculator.RaceCalculator", short_label="Calculator", rail=7,
        keywords=(
            "fuel calculator tyre tire strategy planner energy pit stop stint "
            "carburant calculateur pneus strategie energie arret relais"
        ),
        status="neopedal.ui.quick.race_backend:race_status",
        description="Fuel, energy, tyres and pit stops of a race, live or planned",
        wiki="Race-Calculator",
    ),
    PageSpec(
        "driver_stats_viewer", "Driver Stats", "", "Utilities",  # contact
        "driver_stats_viewer.DriverStatsViewer", short_label="Stats", rail=2,
        description="Your laps, personal bests and progress on every track",
        wiki="Driver-Stats",
    ),
    PageSpec(
        "track_map_viewer", "Track Map Viewer", "", "Utilities",  # map pin
        "track_map_viewer.TrackMapViewer", short_label="Map",
        description="Track maps recorded by the app",
        wiki="Telemetry-Viewer#track-map-viewer",
    ),
    PageSpec(
        "lap_viewer", "Lap Telemetry Viewer", "", "Utilities",  # area chart
        "lap_viewer.LapViewer", short_label="Telemetry", rail=6,
        description="Compare recorded laps on charts and on the track map",
        wiki="Telemetry-Viewer",
    ),
    PageSpec(
        "broadcast_director", "Broadcast Director", "", "Utilities",  # sliders (mixing desk)
        "broadcast_director.BroadcastDirector", short_label="Broadcast", rail=4,
        keywords=(
            "lmu broadcast director cast casting camera cameras spectator stream commentator commentary battle "
            "auto director tv production regie realisateur spectateur commentateur commentaires bagarre diffusion"
        ),
        status="neopedal.ui.quick.director_backend:director_status",
        description="Cameras, live timing and graphics while spectating",
        wiki="Broadcast-Director",
    ),
    PageSpec(
        "race_results_viewer", "Results & Replays", "", "Utilities",  # flag
        "race_results_viewer.RaceResultsViewer", short_label="Results", rail=3,
        keywords=(
            "results classification standings finish position grid laps sectors incidents penalties session "
            "resultats classement arrivee grille tours secteurs incidents penalites "
            "game replays lmu replay incident contact crash watch rediffusion contacts accrochage revoir"
        ),
        description="Results of past sessions and game replays",
        wiki="Race-Results",
    ),
    PageSpec(
        "stream_overlay_view", "Stream Overlays", "", "Utilities",  # streaming
        "stream_overlay_view.StreamOverlaysView", short_label="Stream", rail=5,
        keywords=(
            "obs streamlabs xsplit vmix twitch youtube stream streaming browser source broadcast layout "
            "diffusion direct source navigateur streamer"
        ),
        description="Overlays as browser sources for OBS and other streaming apps",
        wiki="Connections#stream-overlays-obs-streamlabs-xsplit-vmix",
    ),
    # Editors
    PageSpec(
        "heatmap_editor", "Heatmap Editor", "", "Editors",  # color
        "heatmap_editor.HeatmapEditor", short_label="Heatmap",
        description="Color scales of temperatures and wear",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "brake_editor", "Brake Editor", "", "Editors",  # edit
        "brake_editor.BrakeEditor", short_label="Brakes",
        description="Brake temperatures and failure thickness of each car",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "tyre_compound_editor", "Tyre Compound Editor", "", "Editors",  # edit
        "tyre_compound_editor.TyreCompoundEditor", short_label="Compounds",
        description="Tyre compound names, letters and colors",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "vehicle_brand_editor", "Vehicle Brand Editor", "", "Editors",  # tag
        "vehicle_brand_editor.VehicleBrandEditor", short_label="Brands",
        description="Car brands shown by overlays",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "vehicle_class_editor", "Vehicle Class Editor", "", "Editors",  # car
        "vehicle_class_editor.VehicleClassEditor", short_label="Classes",
        description="Class names and colors",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "track_info_editor", "Track Info Editor", "", "Editors",  # info
        "track_info_editor.TrackInfoEditor", short_label="Tracks",
        description="Track details: pit lane, orientation and more",
        wiki="Presets-and-Settings#global-config",
    ),
    PageSpec(
        "track_notes_editor", "Track Notes Editor", "", "Editors",  # quick note
        "track_notes_editor.TrackNotesEditor", short_label="Notes",
        description="Notes shown on a track at a given distance",
        wiki="Telemetry-Viewer",
    ),
    # Management
    PageSpec(
        "app_settings", "Settings", "", "Management",  # settings
        "app_settings.AppSettings",
        keywords=(
            "settings configuration options preferences application config.json overlay style theme notification "
            "compatibility remote control web dashboard vr user path folder language startup update backup "
            "parametres reglages preferences style theme notifications compatibilite controle a distance "
            "tableau de bord dossiers langue demarrage mise a jour sauvegardes"
        ),
        description="Every application option",
        wiki="Presets-and-Settings#global-config",
        listed=False,
    ),
    PageSpec(
        "plugin_manager", "Plugin Manager", "", "Management",  # puzzle
        "plugin_manager.PluginManager", short_label="Plugins",
        description="Install, trust and enable overlay plugins",
        wiki="Overlays#widget-plugins",
    ),
    PageSpec(
        "perf_view", "Overlay Performance", "", "Management",  # speed
        "perf_view.PerformanceView", short_label="Performance",
        description="CPU time of each overlay and module, game data state",
        wiki="Troubleshooting#performance",
    ),
    # Advanced
    PageSpec(
        "replay_view", "Session Recorder", "", "Advanced",  # replay
        "replay_view.ReplayView", short_label="Recorder",
        keywords=(
            "telemetry replay tpreplay record playback without game overlay test "
            "rejeu telemetrie enregistrer lecture sans jeu"
        ),
        description="Record a session and play it back without the game",
        wiki="Connections#session-recorder",
    ),
)


# User guide page of dialog pages absent from PAGES (help button), by dialog class name
DIALOG_WIKI = {
    "OverlayOptions": "Getting-Started#the-overlay-options-page",
    "OptionFinder": "Getting-Started#find-any-option",
    "ReleaseNotesDialog": "Updates-and-Security#whats-new-page",
    "About": "Home#license-and-credits",
    "LogInfo": "Troubleshooting#logs",
    "BugReport": "Troubleshooting#report-a-bug",
    "RailEditor": "Getting-Started#the-main-window",
    "QuickAccessEditor": "Getting-Started#home-page",
}


def check_pages(pages: tuple[PageSpec, ...]):
    """Raise if page names, dialogs or rail positions repeat, or a tool has no known category"""
    names = [page.name for page in pages]
    if len(set(names)) != len(names):
        raise RuntimeError(f"page declared twice: {sorted({name for name in names if names.count(name) > 1})}")
    for page in pages:
        if page.category == PAGE_MAIN:
            if page.dialog:
                raise RuntimeError(f"main page with a dialog: {page.name}")
        elif page.category not in TOOL_CATEGORIES or page.dialog.split(".", 1)[0] != page.name:
            raise RuntimeError(f"tool page without known category or dialog module: {page.name}")
    rails = [page.rail for page in pages if page.rail >= 0]
    if sorted(rails) != list(range(len(rails))):
        raise RuntimeError(f"default rail positions not 0 to {len(rails) - 1}: {sorted(rails)}")


def main_pages(pages: tuple[PageSpec, ...] = PAGES) -> tuple[PageSpec, ...]:
    """Main window pages in tab order"""
    return tuple(page for page in pages if page.category == PAGE_MAIN)


def tool_pages(pages: tuple[PageSpec, ...] = PAGES) -> tuple[PageSpec, ...]:
    """Tool pages in card order (category by category)"""
    return tuple(page for category in TOOL_CATEGORIES for page in pages if page.category == category)


def tool_sections(
    pages: tuple[PageSpec, ...] = PAGES, listed_only: bool = False,
) -> tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]:
    """Tool sections: (title, ((label, glyph, "module.DialogClass"), ...)), empty sections left out

    Args:
        listed_only: only tools of Tools page & Tools menu (see PageSpec.listed), else every tool page
            (navigation rail entries, pages reopened at startup).
    """
    sections = []
    for category in TOOL_CATEGORIES:
        tools = tuple((page.label, page.glyph, page.dialog) for page in pages
                      if page.category == category and (page.listed or not listed_only))
        if tools:
            sections.append((category, tools))
    return tuple(sections)


def page_spec(key: str, pages: tuple[PageSpec, ...] = PAGES) -> PageSpec | None:
    """Page by name (page key, tool module name) or by tool dialog path or class name, None if unknown"""
    for page in pages:
        if key in (page.name, page.dialog) or (page.dialog and page.dialog.rsplit(".", 1)[-1] == key):
            return page
    return None


def page_wiki(class_name: str) -> str:
    """User guide page (and #anchor) of a dialog page by class name: its PageSpec, else DIALOG_WIKI, "" if none"""
    spec = page_spec(class_name)
    return spec.wiki if spec is not None and spec.wiki else DIALOG_WIKI.get(class_name, "")


def default_rail(pages: tuple[PageSpec, ...] = PAGES) -> str:
    """Default navigation rail setting text: page keys in rail order"""
    return ",".join(page.name for page in sorted((page for page in pages if page.rail >= 0), key=lambda page: page.rail))


check_pages(PAGES)
