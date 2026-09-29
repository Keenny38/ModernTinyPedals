"""
Black box live check (requires a running sim, driving on track)

Checks, on live game data, the three things the Black box takes from the game without a way to
verify them offline:
1. Wheel angle sign convention: do both front wheels turn the way the steering wheel does?
2. Suspension force: is it the spring alone (linear with deflection), or does it include
   anti-roll bar / third spring force (then force also follows lateral acceleration)?
3. Impact position: which side does the damage cone point to, for impacts you make on purpose?
Also prints tread temperatures (left / center / right of the car) to check camber readings.

Usage, from project root, while driving (a few corners both ways, a light wall touch if you can):
    python tools/black_box_live_check.py [seconds]
"""

from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAMPLE_INTERVAL = 0.05  # seconds
WHEEL_NAMES = ("FL", "FR", "RL", "RR")


def linear_fit(points: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """(intercept, slope, r squared) of y over x, None if not enough spread"""
    count = len(points)
    if count < 20:
        return None
    mean_x = sum(x for x, _ in points) / count
    mean_y = sum(y for _, y in points) / count
    var_x = sum((x - mean_x) ** 2 for x, _ in points)
    var_y = sum((y - mean_y) ** 2 for _, y in points)
    if var_x <= 1e-9 or var_y <= 1e-9:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = cov / var_x
    return mean_y - slope * mean_x, slope, cov * cov / (var_x * var_y)


def correlation(pairs: list[tuple[float, float]]) -> float:
    fit = linear_fit(pairs)
    if fit is None:
        return 0.0
    return math.copysign(math.sqrt(fit[2]), fit[1])


def main(duration: float):
    from tinypedal import calculation as calc
    from tinypedal.api_control import api
    from tinypedal.const_file import FileExt
    from tinypedal.setting import cfg
    from tinypedal.widget._black_box.state import SteerConvention, impact_arrow

    cfg.load_global()
    cfg.set_next_to_load(f"{cfg.preset_files()[0]}{FileExt.JSON}")
    cfg.load_user()
    api.connect()
    api.start()
    print(f"Reading {api.read.vehicle.vehicle_name() or '(no car)'} for {duration:.0f} s, drive a few corners both ways")

    convention = SteerConvention()
    susp_points: list[list[tuple[float, float]]] = [[] for _ in range(4)]
    susp_lateral: list[list[tuple[float, float]]] = [[] for _ in range(4)]
    last_position = [math.nan] * 4
    last_impact = api.read.vehicle.impact_time()
    impacts = []
    temps = []
    end = time.monotonic() + duration
    try:
        while time.monotonic() < end:
            toe = [math.degrees(value) for value in api.read.wheel.toe()]
            convention.update(toe[0], toe[1], api.read.inputs.steering())
            positions = api.read.wheel.suspension_deflection()
            forces = api.read.wheel.suspension_force()
            lateral = api.read.vehicle.acceleration_lateral()
            for index in range(4):
                speed = (positions[index] - last_position[index]) / SAMPLE_INTERVAL
                last_position[index] = positions[index]
                if api.read.vehicle.speed() > 10 and abs(speed) < 50:  # low damper speed: spring force
                    susp_points[index].append((positions[index], forces[index]))
                    susp_lateral[index].append((lateral, forces[index]))
            impact = api.read.vehicle.impact_time()
            if impact > last_impact > 0 or (impact > 0 >= last_impact):
                position = api.read.vehicle.impact_position()
                impacts.append((position, impact_arrow(calc.degrees(calc.oriyaw(*position)))))
                print(f"  impact at {impact:.1f}s, position {position}, cone arrow {impacts[-1][1]}")
            last_impact = impact
            if api.read.vehicle.speed() > 20:
                temps.append(api.read.tyre.surface_temperature_ico())
            time.sleep(SAMPLE_INTERVAL)
    finally:
        api.stop()

    print("\n1. Wheel angle sign")
    votes = convention.mirror + convention.same
    if votes < 15:
        print(f"  not enough steered samples ({votes}), steer more (over 1 degree of wheel angle)")
    else:
        print(f"  both front wheels same sign: {convention.same}, opposite: {convention.mirror}"
              f" -> {'toe-in per wheel (right side flipped)' if convention.mirrored else 'vehicle frame'}")
        print(f"  front left along steering: {convention.keep}, against: {convention.invert}"
              f" -> positive means {'left (flipped)' if convention.inverted else 'right'}")
        print("  The Black box learns this by itself; check that tyres turn the way you steer.")

    print("\n2. Suspension force")
    for index, name in enumerate(WHEEL_NAMES):
        fit = linear_fit(susp_points[index])
        if fit is None:
            print(f"  {name}: not enough data")
            continue
        intercept, rate, r_squared = fit
        residuals = [(lat, force - (intercept + rate * pos))
                     for (pos, force), (lat, _) in zip(susp_points[index], susp_lateral[index])]
        roll = correlation(residuals)
        print(f"  {name}: spring rate {rate:.0f} N/mm, linear fit R2 {r_squared:.2f}, "
              f"residual vs lateral g {roll:+.2f}")
    print("  R2 near 1 and residual correlation near 0: spring force alone, bump stop detection reliable.")
    print("  Residual strongly following lateral g: anti-roll bar in the force, raise suspension_bump_force_margin.")

    print("\n3. Impact position")
    if not impacts:
        print("  no impact recorded: touch a wall lightly with a known side, then run again")
    for position, arrow in impacts:
        print(f"  position {position} -> cone arrow {arrow} (compare with the side you hit)")

    print("\n4. Tread temperatures (left / center / right of the car), average while driving")
    if temps:
        for index, name in enumerate(WHEEL_NAMES):
            left, center, right = (sum(sample[index * 3 + band] for sample in temps) / len(temps)
                                   for band in range(3))
            inner, outer = (left, right) if index % 2 else (right, left)
            print(f"  {name}: {left:.0f} / {center:.0f} / {right:.0f}  inner-outer {inner - outer:+.0f}")
        print("  With negative camber, inner should be hotter (positive inner-outer) on all 4 wheels.")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 60.0)
