"""
Example plugin widget: speed & gear

Copy this folder to create your own widget:
    plugins/<your_name>/setting.json   default options (base options are added automatically)
    plugins/<your_name>/widget.py      Realtime class

Your widget appears as "plugin_<your_name>" in Widget tab.
"""

from tinypedal.api_control import api
from tinypedal.widget._base import Overlay


class Realtime(Overlay):
    """Draw widget"""

    def __init__(self, config, widget_name):
        # Assign base setting (reads options from setting.json & user preset into self.wcfg)
        super().__init__(config, widget_name)
        layout = self.set_grid_layout(gap=self.wcfg["bar_gap"])
        self.set_primary_layout(layout=layout)

        # Config font
        font = self.config_font(self.wcfg["font_name"], self.wcfg["font_size"], self.wcfg["font_weight"])
        self.setFont(font)
        font_m = self.get_font_metrics(font)
        padding = self.set_padding(self.wcfg["font_size"], self.wcfg["bar_padding"])

        # Speed bar
        self.bar_speed = self.set_rawtext(
            text="---",
            width=font_m.width * 7 + padding,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg["font_color"],
            bg_color=self.wcfg["background_color"],
            last=-1,
        )
        # Gear bar
        self.bar_gear = self.set_rawtext(
            text="N",
            width=font_m.width * 2 + padding,
            fixed_height=font_m.height,
            offset_y=font_m.voffset,
            fg_color=self.wcfg["font_color_gear"],
            bg_color=self.wcfg["background_color_gear"],
            last=-2,
        )
        layout.addWidget(self.bar_gear, 0, 0)
        layout.addWidget(self.bar_speed, 0, 1)

    def timerEvent(self, event):
        """Update when vehicle on track (called every update_interval ms)"""
        speed = round(api.read.vehicle.speed() * 3.6)  # m/s to km/h
        if self.bar_speed.last != speed:  # only repaint on change
            self.bar_speed.last = speed
            self.bar_speed.text = f"{speed:3d} kph"
            self.bar_speed.update()

        gear = api.read.engine.gear()
        if self.bar_gear.last != gear:
            self.bar_gear.last = gear
            self.bar_gear.text = "R" if gear < 0 else ("N" if gear == 0 else str(gear))
            self.bar_gear.update()
