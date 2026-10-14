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
Brands preset function
"""

from __future__ import annotations

from collections import OrderedDict

from ..api_control import api
from ..const_file import ConfigType
from ..demo_state import demo_reader
from ..regex_pattern import rex_lmu_brand_extract
from ..setting import cfg

# Vehicle name & model whose brand was not found: not searched again at every update (bounded, oldest dropped)
NO_BRAND_SIZE = 512
_no_brand: OrderedDict[tuple[str, str], None] = OrderedDict()


def extract_lmu_brand_name(value: str, default: str) -> str:
    """Extract LMU brand name from vehicle model

    Extraction pattern assumes:
        - No numbers in name.
        - Max of 2 words.
        - Minimum of 2 letters for first word.
        - Minimum of 3 letters for second word (optional), must be in title case.
    """
    try:
        match_obj = rex_lmu_brand_extract.search(value)
    except (TypeError, ValueError):
        return default
    if match_obj is None:
        return default
    return match_obj.group().strip()


def select_brand_name(index: int | None = None, vehicle_name: str = "") -> str:
    """Select brand name from brands preset, returns empty string if not found"""
    brand_name = cfg.user.brands.get(vehicle_name)
    if brand_name is None:
        demo = demo_reader()  # overlay picture on simulated race: its car, never saved
        model = (api.read if demo is None else demo).vehicle.vehicle_model(index)
        key = (vehicle_name, model if isinstance(model, str) else "")
        if demo is None and key in _no_brand:  # searched before, model unchanged
            return ""
        brand_name = extract_lmu_brand_name(model, "")
        if demo is None:
            if brand_name:  # save brand name if valid
                cfg.user.brands[vehicle_name] = brand_name
                cfg.save(config_type=ConfigType.BRANDS)
            else:
                _no_brand[key] = None
                if len(_no_brand) > NO_BRAND_SIZE:
                    _no_brand.popitem(last=False)
    return brand_name
