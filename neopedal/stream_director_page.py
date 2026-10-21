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
Broadcast graphics page (browser source /director of the stream overlay server): HTML & style of the transparent
16:9 page, compound badges & status colors filled in (director_html); script of the page in stream_director_script
"""

from __future__ import annotations

import json
from html import escape

from .stream_director_script import DIRECTOR_SCRIPT
from .template.setting_compounds import COMPOUND_SYMBOLS, letter_color
from .template.setting_status_colors import ENERGY_LOW, ENERGY_MEDIUM, status_css


def tyre_badges() -> dict[str, tuple[str, str]]:
    """Compound badge of each letter, as in overlays: (fill, readable letter color)"""
    badges = {}
    for letter in COMPOUND_SYMBOLS:
        fill = letter_color(letter)
        red, green, blue = (int(fill[index:index + 2], 16) / 255 for index in (1, 3, 5))
        light = 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.55
        badges[letter.upper()] = (fill, "#0E1116" if light else "#F4F6F9")
    return badges


def director_html(language: str, title: str) -> str:
    return (DIRECTOR_HTML.replace("@@lang@@", escape(language)).replace("@@title@@", escape(title))
            .replace("@@tyres@@", json.dumps(tyre_badges())).replace("@@status@@", status_css())
            .replace("@@energyLow@@", str(ENERGY_LOW)).replace("@@energyMedium@@", str(ENERGY_MEDIUM)))


# Transparent 16:9 page, sized from the page height (vh): 1920x1080 browser source in OBS, Streamlabs, vMix...
# Query: animate=0 (no animation), once=1 (asked once: screenshots), scale=<factor>, only=<ids> (these graphics
# only, e.g. only=tower,map: graphics split over several sources), preset=<pre|race|post> (layout preset of this
# source, else the one in use), edit=1 (layout editor: sample data, drag graphics to move them, wheel to resize,
# saved for every source)
DIRECTOR_PAGE = """<!doctype html><html lang="@@lang@@"><head><meta charset="utf-8"><title>@@title@@</title>
<style>
@font-face{font-family:"Barlow Semi Condensed";font-weight:500;src:url(/fonts/BarlowSemiCondensed-Medium.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:600;src:url(/fonts/BarlowSemiCondensed-SemiBold.ttf)}
@font-face{font-family:"Barlow Semi Condensed";font-weight:700;src:url(/fonts/BarlowSemiCondensed-Bold.ttf)}
:root{--u:1vh;--op:.92;--panel:rgba(11,13,19,var(--op));--panel2:rgba(22,25,34,var(--op));--line:rgba(255,255,255,.08);
--text:#f5f7fb;--dim:rgba(230,235,244,.64);--accent:#e5383b;@@status@@
--blue:#60a5fa;--ar:229,56,59;--ease:cubic-bezier(.2,.8,.2,1)}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden;background:transparent}
body{font-family:"Barlow Semi Condensed","Segoe UI",sans-serif;color:var(--text);font-weight:500;
font-variant-numeric:tabular-nums;font-size:calc(var(--u)*2)}
.panel{background:var(--panel);border-radius:calc(var(--u)*.9);box-shadow:0 calc(var(--u)*1) calc(var(--u)*3.4) rgba(0,0,0,.45);overflow:hidden}
.g{position:absolute}
.g.off{display:none!important}
.show{opacity:1!important;transform:none!important}
.still *{transition:none!important;animation:none!important}
.hidden-all>.g{opacity:0!important}
.accentbg{background:linear-gradient(90deg,var(--accent),rgba(var(--ar),.35) 70%,rgba(var(--ar),0))}
/* Tower: rows placed by translateY (moves animated) */
#tower{left:calc(var(--u)*2.6);top:calc(var(--u)*3);width:calc(var(--u)*38);opacity:0;
transform:translateX(calc(var(--u)*-3));transition:opacity .5s,transform .5s var(--ease)}
#tower header{display:flex;align-items:center;gap:calc(var(--u)*1);padding:calc(var(--u)*1) calc(var(--u)*1.4);font-weight:700}
#towerTitle{font-size:calc(var(--u)*2.1);letter-spacing:.06em;text-transform:uppercase;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#towerSub{font-size:calc(var(--u)*1.6);color:rgba(255,255,255,.85)}
#towerRows{position:relative;overflow:hidden;transition:height .4s var(--ease)}
#towerThumb{position:absolute;right:calc(var(--u)*.15);top:0;width:calc(var(--u)*.4);z-index:1;display:none;background:rgba(255,255,255,.5);
border-radius:calc(var(--u)*.2);transition:top .6s var(--ease),height .4s var(--ease)}
.trow{position:absolute;left:0;right:0;top:0;display:grid;grid-template-columns:calc(var(--u)*3.4) calc(var(--u)*.45) calc(var(--u)*4.6) minmax(0,1fr) auto calc(var(--u)*7.6);
align-items:center;column-gap:calc(var(--u)*.9);height:calc(var(--u)*3.3);padding:0 calc(var(--u)*1.2);
border-bottom:1px solid var(--line);transition:transform .6s var(--ease),background .3s,opacity .4s}
.trow.new{opacity:0}
.trow.air{background:linear-gradient(90deg,rgba(var(--ar),.42),rgba(var(--ar),.08))}
.thead{position:absolute;left:0;right:0;top:0;height:calc(var(--u)*2.4);display:flex;align-items:center;gap:calc(var(--u)*.8);
padding:0 calc(var(--u)*1.2);font-size:calc(var(--u)*1.5);font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);
background:rgba(255,255,255,.04);transition:transform .6s var(--ease)}
.thead i{width:calc(var(--u)*1.1);height:calc(var(--u)*1.1);border-radius:50%}
.tpos{font-weight:700;text-align:right;font-size:calc(var(--u)*2.1)}
.tbar{height:62%;border-radius:calc(var(--u)*.3)}
.tnum{color:var(--dim);font-size:calc(var(--u)*1.7)}
.tname{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-transform:uppercase;letter-spacing:.02em}
.tgap{text-align:right;color:var(--dim);font-size:calc(var(--u)*1.8);white-space:nowrap}
.tgap.close{color:var(--loss);font-weight:700}
.tgap.lap{color:var(--gold);font-weight:700}.tgap.lap.fastest{color:var(--purple)}
.tgap .tpit{display:inline-block;padding:0 calc(var(--u)*.6);border-radius:calc(var(--u)*.4);background:rgba(251,146,60,.22);color:var(--warn);font-weight:700;font-size:calc(var(--u)*1.5)}
.tgap .tpit.garage{background:rgba(255,255,255,.1);color:var(--dim)}.tgap .tpit.dnf,.tgap .tpit.dq{background:rgba(248,113,113,.22);color:var(--loss)}
.tchange{font-size:calc(var(--u)*1.2);margin-left:calc(var(--u)*.4)}
.tchange.up{color:var(--gain)}.tchange.down{color:var(--loss)}
.tmarks{display:flex;align-items:center;gap:calc(var(--u)*.3)}
.tyre{width:calc(var(--u)*1.7);height:calc(var(--u)*1.7);border-radius:calc(var(--u)*.34);display:flex;
align-items:center;justify-content:center;font-size:calc(var(--u)*1);font-weight:700}
.tpen{padding:0 calc(var(--u)*.45);border-radius:calc(var(--u)*.3);background:var(--loss);color:#fff;font-weight:700;font-size:calc(var(--u)*1.25)}
.tfl{padding:0 calc(var(--u)*.45);border-radius:calc(var(--u)*.3);background:var(--purple);color:#111;font-weight:700;font-size:calc(var(--u)*1.25)}
.tstops{color:var(--dim);font-size:calc(var(--u)*1.3);font-weight:700}
/* Driver card */
#card{left:calc(var(--u)*6);bottom:calc(var(--u)*7);min-width:calc(var(--u)*62);max-width:calc(var(--u)*92);
display:flex;align-items:stretch;opacity:0;transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#cardPlace{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:calc(var(--u)*11);
padding:0 calc(var(--u)*1.6);font-weight:700;background:var(--accent)}
#cardPlace b{font-size:calc(var(--u)*5.6);line-height:1}
#cardPlace span{font-size:calc(var(--u)*1.6);letter-spacing:.12em;text-transform:uppercase;opacity:.9}
#cardBody{flex:1;padding:calc(var(--u)*1.2) calc(var(--u)*2);display:flex;flex-direction:column;justify-content:center;
gap:calc(var(--u)*.3);background:var(--panel)}
#cardTop{display:flex;align-items:center;gap:calc(var(--u)*1.2)}
#cardNum{font-size:calc(var(--u)*2.6);color:var(--dim);font-weight:700}
#cardName{font-size:calc(var(--u)*4);font-weight:700;line-height:1.05;text-transform:uppercase;letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cardLogo{height:calc(var(--u)*3.6);max-width:calc(var(--u)*9);object-fit:contain;margin-left:auto;display:none}
#cardTeam{color:var(--dim);font-size:calc(var(--u)*2.1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#cardStats{display:flex;gap:calc(var(--u)*2.2);font-size:calc(var(--u)*1.9);margin-top:calc(var(--u)*.3)}
#cardStats i{font-style:normal;color:var(--dim);margin-right:calc(var(--u)*.5);text-transform:uppercase;font-size:calc(var(--u)*1.5);letter-spacing:.08em}
#cardStory{align-self:flex-start;margin-top:calc(var(--u)*.4);padding:calc(var(--u)*.2) calc(var(--u)*1);border-radius:calc(var(--u)*.5);
background:rgba(255,255,255,.1);font-size:calc(var(--u)*1.5);font-weight:700;letter-spacing:.1em;text-transform:uppercase;display:none}
#cardPicture{width:calc(var(--u)*22);object-fit:cover;display:none;background:var(--panel2)}
/* Battle: two cars, or contact of an instant replay */
#battle{left:calc(50vw - var(--u)*39);bottom:calc(var(--u)*7);width:calc(var(--u)*78);
opacity:0;transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#battle header,#train header{text-align:center;padding:calc(var(--u)*.7);font-weight:700;letter-spacing:.14em;text-transform:uppercase;
font-size:calc(var(--u)*1.8);background:linear-gradient(90deg,rgba(var(--ar),0),var(--accent),rgba(var(--ar),0))}
#battleBody{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:calc(var(--u)*1.4) calc(var(--u)*2)}
.bside{display:flex;flex-direction:column;gap:calc(var(--u)*.2);min-width:0}
.bside.right{text-align:right}
.bnum{color:var(--dim);font-weight:700;font-size:calc(var(--u)*2)}
.bname{font-size:calc(var(--u)*3);font-weight:700;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bteam{color:var(--dim);font-size:calc(var(--u)*1.7);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#battleGap{text-align:center;padding:0 calc(var(--u)*2.4)}
#battleGap b{display:block;font-size:calc(var(--u)*4.4);line-height:1}
#battleGap span{font-size:calc(var(--u)*1.6);color:var(--dim)}
#battleGap span.closing{color:var(--loss)}#battleGap span.opening{color:var(--gain)}
/* Battle train: up to 6 cars of a class close together */
#train{left:calc(50vw - var(--u)*60);bottom:calc(var(--u)*7);width:calc(var(--u)*120);opacity:0;
transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
#trainCars{display:flex;padding:calc(var(--u)*1) calc(var(--u)*1.2);gap:calc(var(--u)*.8)}
.tcard{flex:1;min-width:0;display:flex;flex-direction:column;gap:calc(var(--u)*.2);padding:calc(var(--u)*.8) calc(var(--u)*1);
border-radius:calc(var(--u)*.6);background:var(--panel2);border-top:calc(var(--u)*.4) solid #888}
.tcard.air{background:rgba(var(--ar),.32)}
.tcard b{font-size:calc(var(--u)*2.6);line-height:1}
.tcard .bname{font-size:calc(var(--u)*2)}
.tcard .tgap{text-align:left}
/* Banners */
#banners{left:50%;top:calc(var(--u)*3);transform:translateX(-50%);display:flex;flex-direction:column;
align-items:center;gap:calc(var(--u)*.8)}
.banner{display:flex;align-items:stretch;opacity:0;transform:translateY(calc(var(--u)*-2));transition:opacity .4s,transform .5s var(--ease)}
.banner .tag{padding:calc(var(--u)*.8) calc(var(--u)*1.4);font-weight:700;letter-spacing:.12em;text-transform:uppercase;
font-size:calc(var(--u)*1.7);display:flex;align-items:center;color:#111}
.banner .txt{padding:calc(var(--u)*.8) calc(var(--u)*1.8);background:var(--panel);display:flex;flex-direction:column;justify-content:center}
.banner .txt b{font-size:calc(var(--u)*2.3);white-space:nowrap}
.banner .txt span{font-size:calc(var(--u)*1.6);color:var(--dim);white-space:nowrap}
/* Replay & clock */
#replay{right:calc(var(--u)*3);top:calc(var(--u)*3);padding:calc(var(--u)*.9) calc(var(--u)*1.8);
background:var(--accent);font-weight:700;letter-spacing:.24em;font-size:calc(var(--u)*2.4);border-radius:calc(var(--u)*.6);
opacity:0;transition:opacity .35s;display:flex;align-items:center;gap:calc(var(--u)*1)}
#replay i{width:calc(var(--u)*1.4);height:calc(var(--u)*1.4);border-radius:50%;background:#fff}
#replay.show i{animation:blink 1.2s infinite}
@keyframes blink{50%{opacity:.25}}
#clock{right:calc(var(--u)*3);bottom:calc(var(--u)*3);display:flex;align-items:center;
gap:calc(var(--u)*1.4);padding:calc(var(--u)*.9) calc(var(--u)*1.6);opacity:0;transition:opacity .5s}
#clockTime{font-size:calc(var(--u)*2.8);font-weight:700}
#clockLabel{font-size:calc(var(--u)*1.4);color:var(--dim);letter-spacing:.12em;text-transform:uppercase}
#clockFlag{padding:calc(var(--u)*.2) calc(var(--u)*.8);border-radius:calc(var(--u)*.4);background:var(--gold);color:#111;font-weight:700;
font-size:calc(var(--u)*1.5);display:none}
#weather{font-size:calc(var(--u)*1.7);color:var(--dim)}
/* Pit radar: cars near the car on air in the pit lane */
#pitradar{right:calc(var(--u)*3);top:calc(var(--u)*46);width:calc(var(--u)*36);opacity:0;
transform:translateX(calc(var(--u)*3));transition:opacity .4s,transform .5s var(--ease)}
#pitradar header{display:flex;align-items:baseline;gap:calc(var(--u)*1);padding:calc(var(--u)*.8) calc(var(--u)*1.4);
background:linear-gradient(90deg,var(--warn),rgba(251,146,60,.25));color:#111;font-weight:700}
#pitTitle{letter-spacing:.14em;text-transform:uppercase;font-size:calc(var(--u)*1.8)}
#pitCount{margin-left:auto;font-size:calc(var(--u)*1.6)}
.prow{display:grid;grid-template-columns:calc(var(--u)*.45) calc(var(--u)*4.6) minmax(0,1fr) auto;align-items:center;
column-gap:calc(var(--u)*.9);height:calc(var(--u)*3.2);padding:0 calc(var(--u)*1.2);border-bottom:1px solid var(--line)}
.prow .tname{font-size:calc(var(--u)*1.9)}
.pdist{text-align:right;font-weight:700;font-size:calc(var(--u)*2)}
.pdist.near{padding:0 calc(var(--u)*.7);border-radius:calc(var(--u)*.4);background:var(--loss);color:#fff;letter-spacing:.1em}
.pdist i{font-style:normal;color:var(--dim);font-weight:500;margin-right:calc(var(--u)*.5)}
/* Onboard: shift lights, speed, gear, pedals, energy & hybrid of the car on air */
#onboard{right:calc(var(--u)*3);bottom:calc(var(--u)*11);opacity:0;transform:translateY(calc(var(--u)*2));
transition:opacity .4s,transform .5s var(--ease)}
.ob-head{display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.6) calc(var(--u)*1.2);font-weight:700;
font-size:calc(var(--u)*1.7);text-transform:uppercase;letter-spacing:.04em;border-left:calc(var(--u)*.5) solid #888}
.ob-head span{color:var(--dim)}
.ob-head em{margin-left:auto;font-style:normal;color:var(--gold);font-size:calc(var(--u)*1.6)}
.ob-leds{display:flex;gap:calc(var(--u)*.4);justify-content:center;padding:calc(var(--u)*.5) calc(var(--u)*1.4) 0}
.ob-leds i{width:calc(var(--u)*1.5);height:calc(var(--u)*1.5);border-radius:50%;background:rgba(255,255,255,.1)}
/* led-* classes: "g" is the class of every graphic (absolute place), never on a part of one */
.ob-leds i{flex:none}.ob-leds i.on.led-g{background:var(--gain)}.ob-leds i.on.led-y{background:var(--gold)}
.ob-leds i.on.led-r{background:var(--loss)}
.ob-leds.flash i{background:var(--blue)!important;animation:blink .25s infinite}
.ob-main{display:flex;align-items:stretch;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1) calc(var(--u)*1.4)}
.ob-speed{display:flex;flex-direction:column;justify-content:center;min-width:calc(var(--u)*10)}
.ob-speed b{font-size:calc(var(--u)*5);line-height:1}
.ob-speed span{color:var(--dim);font-size:calc(var(--u)*1.5);text-transform:uppercase;letter-spacing:.1em}
.ob-gear{display:flex;align-items:center;justify-content:center;min-width:calc(var(--u)*7);font-size:calc(var(--u)*6);font-weight:700;
border-radius:calc(var(--u)*.7);background:var(--panel2)}
.ob-pedals{display:flex;gap:calc(var(--u)*.6);align-items:flex-end}
.ob-pedal{width:calc(var(--u)*1.6);height:calc(var(--u)*7);border-radius:calc(var(--u)*.4);background:rgba(255,255,255,.08);
position:relative;overflow:hidden}
.ob-pedal i{position:absolute;left:0;right:0;bottom:0;height:0}
.ob-energy{display:flex;align-items:center;gap:calc(var(--u)*.8);padding:calc(var(--u)*.4) calc(var(--u)*1.4) calc(var(--u)*.6);
color:var(--dim);font-size:calc(var(--u)*1.4);text-transform:uppercase;letter-spacing:.08em}
.ob-energy:last-child{padding-bottom:calc(var(--u)*1)}
.ob-energy span{min-width:calc(var(--u)*8)}
.ob-energy div{flex:1;height:calc(var(--u)*.7);border-radius:calc(var(--u)*.35);background:rgba(255,255,255,.08);overflow:hidden}
.ob-energy i{display:block;height:100%;background:var(--gain);transition:width .2s linear,background-color .3s}
#onboard.cockpit .ob-main{flex-direction:column;align-items:center}
#onboard.cockpit .ob-gear{min-width:calc(var(--u)*14);min-height:calc(var(--u)*11);border-radius:50%;font-size:calc(var(--u)*7)}
#onboard.cockpit .ob-speed{align-items:center}
#onboard.helmet{border-radius:calc(var(--u)*.5)}
#onboard.helmet .ob-main{padding:calc(var(--u)*.5) calc(var(--u)*1)}
#onboard.helmet .ob-gear{min-width:calc(var(--u)*4.5);font-size:calc(var(--u)*3.4);background:none}
#onboard.helmet .ob-speed b{font-size:calc(var(--u)*3.4)}
#onboard.helmet .ob-pedal{width:calc(var(--u)*1);height:calc(var(--u)*4)}
#onboard.helmet .ob-head,#onboard.helmet .ob-energy{display:none}
/* Qualifying lap of the car on air */
#quali{left:calc(50vw - var(--u)*40);bottom:calc(var(--u)*7);width:calc(var(--u)*80);opacity:0;
transform:translateY(calc(var(--u)*3));transition:opacity .45s,transform .55s var(--ease)}
.q-top{display:flex;align-items:center;gap:calc(var(--u)*1.2);padding:calc(var(--u)*1) calc(var(--u)*1.6);border-left:calc(var(--u)*.6) solid #888}
.q-pos{font-size:calc(var(--u)*3.4);font-weight:700}
.q-name{flex:1;min-width:0;font-size:calc(var(--u)*2.8);font-weight:700;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.q-time{font-size:calc(var(--u)*4);font-weight:700}
.q-status{padding:calc(var(--u)*.2) calc(var(--u)*.9);border-radius:calc(var(--u)*.4);background:rgba(255,255,255,.12);font-weight:700;
font-size:calc(var(--u)*1.5);letter-spacing:.1em;text-transform:uppercase}
.q-bottom{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:calc(var(--u)*.6);padding:0 calc(var(--u)*1.6) calc(var(--u)*1.2)}
.q-sector{padding:calc(var(--u)*.4) calc(var(--u)*.8);border-radius:calc(var(--u)*.4);background:var(--panel2);text-align:center;
font-size:calc(var(--u)*1.9);font-weight:700;border-bottom:calc(var(--u)*.4) solid rgba(255,255,255,.12)}
.q-target{display:flex;flex-direction:column;align-items:flex-end;justify-content:center;font-size:calc(var(--u)*1.5);color:var(--dim)}
.q-target b{font-size:calc(var(--u)*2.4)}
/* Track map: no panel, shadow keeps it readable on any picture. Shadow of the track lines drawn once in its own
svg layer behind (blurred copy: two shadows of 0.35 & 0.9 u as before), never blurred again while cars move */
#map{right:calc(var(--u)*3);top:calc(var(--u)*11);width:calc(var(--u)*40);padding:calc(var(--u)*1.2);opacity:0;transition:opacity .5s}
#map svg{display:block;width:100%;height:auto;overflow:visible;position:relative}
#map svg#mapShade{position:absolute;left:calc(var(--u)*1.2);top:calc(var(--u)*1.2);width:calc(100% - var(--u)*2.4);
will-change:transform;pointer-events:none}
#mapSvg{will-change:transform}
.msector{fill:none;stroke:rgba(255,255,255,.92);stroke-linejoin:round;stroke-linecap:round;transition:stroke .4s}
.msector.yellow{stroke:var(--gold)}
#mapPit{fill:none;stroke:rgba(255,255,255,.45);stroke-dasharray:6 6}
.mcar{transition:transform .22s linear,opacity .4s}
.mcar.pit{opacity:.35}
.mcar text{font-weight:700;fill:#fff;text-anchor:middle;dominant-baseline:central}
.myellow{animation:blink 0.8s infinite}
/* On demand: starting grid, event card, classification, championship */
.board{left:calc(50vw - var(--u)*62);top:calc(var(--u)*14);width:calc(var(--u)*124);opacity:0;transform:translateY(calc(var(--u)*3));
transition:opacity .5s,transform .6s var(--ease)}
.board header{display:flex;align-items:center;gap:calc(var(--u)*1.4);padding:calc(var(--u)*1.4) calc(var(--u)*2)}
.board header b{font-size:calc(var(--u)*3);font-weight:700;text-transform:uppercase;letter-spacing:.06em}
.board header span{font-size:calc(var(--u)*2);color:rgba(255,255,255,.85)}
.board header em{margin-left:auto;font-style:normal;font-size:calc(var(--u)*1.6);color:rgba(255,255,255,.8)}
#gridCars{display:grid;grid-template-columns:1fr 1fr;gap:calc(var(--u)*1) calc(var(--u)*2);padding:calc(var(--u)*1.6) calc(var(--u)*2)}
.gcar{display:flex;align-items:center;gap:calc(var(--u)*1.2);padding:calc(var(--u)*.8) calc(var(--u)*1.2);border-radius:calc(var(--u)*.6);
background:var(--panel2);border-left:calc(var(--u)*.6) solid #888}
.gcar:nth-child(even){margin-top:calc(var(--u)*3)}
.gcar b{font-size:calc(var(--u)*3.4);min-width:calc(var(--u)*4.4);text-align:center}
.gcar div{flex:1;min-width:0}
.gcar img{height:calc(var(--u)*6);width:calc(var(--u)*13);object-fit:cover;border-radius:calc(var(--u)*.4)}
.gtime{font-size:calc(var(--u)*2);font-weight:700}
#eventBody{display:grid;grid-template-columns:auto 1fr;gap:calc(var(--u)*2);padding:calc(var(--u)*2)}
#eventLogo{height:calc(var(--u)*14);max-width:calc(var(--u)*30);object-fit:contain;display:none}
.ev-cond{font-size:calc(var(--u)*2.2);margin-bottom:calc(var(--u)*1.2)}
.ev-cast{display:flex;gap:calc(var(--u)*1);margin-bottom:calc(var(--u)*1.4)}
.ev-node{flex:1;padding:calc(var(--u)*.8);border-radius:calc(var(--u)*.6);background:var(--panel2);text-align:center}
.ev-node.wet{background:rgba(96,165,250,.25)}
.ev-node b{display:block;font-size:calc(var(--u)*2.2)}
.ev-node span{display:block;color:var(--dim);font-size:calc(var(--u)*1.5)}
.ev-row{display:flex;justify-content:space-between;font-size:calc(var(--u)*2);padding:calc(var(--u)*.4) 0;border-bottom:1px solid var(--line)}
.ev-row span{color:var(--dim)}
.rrow{display:grid;grid-template-columns:calc(var(--u)*4) calc(var(--u)*.5) calc(var(--u)*5) minmax(0,1.4fr) minmax(0,1fr) calc(var(--u)*6) calc(var(--u)*11) calc(var(--u)*11) calc(var(--u)*6);
align-items:center;column-gap:calc(var(--u)*1.2);height:calc(var(--u)*3.6);padding:0 calc(var(--u)*2);border-bottom:1px solid var(--line);font-size:calc(var(--u)*2)}
.rrow.head{height:calc(var(--u)*3);color:var(--dim);font-size:calc(var(--u)*1.5);letter-spacing:.1em;text-transform:uppercase}
.rrow .r{text-align:right}.rrow .out{color:var(--loss);font-weight:700}
.crow{display:grid;grid-template-columns:calc(var(--u)*5) calc(var(--u)*.5) minmax(0,1.4fr) minmax(0,1fr) calc(var(--u)*16);
align-items:center;column-gap:calc(var(--u)*1.2);height:calc(var(--u)*3.8);padding:0 calc(var(--u)*2);border-bottom:1px solid var(--line);font-size:calc(var(--u)*2.1)}
.medal{display:inline-flex;align-items:center;justify-content:center;width:calc(var(--u)*3.2);height:calc(var(--u)*3.2);border-radius:50%;font-weight:700}
.medal.m1{background:#facc15;color:#111}.medal.m2{background:#cbd5e1;color:#111}.medal.m3{background:#d97706;color:#111}
.cpts{text-align:right;font-weight:700;font-size:calc(var(--u)*2.4);white-space:nowrap}
.pagebar{height:calc(var(--u)*.4);background:var(--accent);width:0}
/* Message of the operator (lower third), countdown, league logo, sponsors */
#message{left:calc(var(--u)*6);bottom:calc(var(--u)*24);display:flex;align-items:stretch;max-width:calc(var(--u)*110);opacity:0;
transform:translateX(calc(var(--u)*-3));transition:opacity .45s,transform .55s var(--ease)}
#messageTitle{padding:calc(var(--u)*1) calc(var(--u)*1.6);background:var(--accent);font-weight:700;letter-spacing:.12em;text-transform:uppercase;
font-size:calc(var(--u)*1.8);display:flex;align-items:center}
#messageText{padding:calc(var(--u)*1) calc(var(--u)*2);font-size:calc(var(--u)*2.6);font-weight:700}
#countdown{left:calc(50vw - var(--u)*30);top:calc(var(--u)*36);width:calc(var(--u)*60);text-align:center;opacity:0;
transform:scale(.96);transition:opacity .5s,transform .6s var(--ease)}
#countdown header{padding:calc(var(--u)*1);font-weight:700;letter-spacing:.2em;text-transform:uppercase;font-size:calc(var(--u)*2)}
#countdownTime{font-size:calc(var(--u)*11);font-weight:700;line-height:1.1;padding:calc(var(--u)*1) 0 calc(var(--u)*2)}
#logo{left:calc(var(--u)*42);top:calc(var(--u)*3);display:flex;align-items:center;gap:calc(var(--u)*1.2);opacity:0;transition:opacity .5s}
#logo img{height:calc(var(--u)*7);max-width:calc(var(--u)*24);object-fit:contain;display:none;filter:drop-shadow(0 0 calc(var(--u)*.4) rgba(0,0,0,.6))}
#logoName{font-size:calc(var(--u)*2.4);font-weight:700;text-transform:uppercase;letter-spacing:.08em;text-shadow:0 0 calc(var(--u)*.6) rgba(0,0,0,.9)}
#sponsors{left:calc(50vw - var(--u)*16);bottom:calc(var(--u)*1.2);width:calc(var(--u)*32);height:calc(var(--u)*5);opacity:0;transition:opacity .5s}
#sponsors img,#sponsors span{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%;object-fit:contain;opacity:0;transition:opacity .8s}
#sponsors span{display:flex;align-items:center;justify-content:center;font-weight:700;font-size:calc(var(--u)*2.2);text-transform:uppercase;letter-spacing:.1em}
#sponsors .on{opacity:1}
/* Layout editor */
body.edit{background:repeating-conic-gradient(#1b1f27 0 25%,#232833 0 50%) 0 0/40px 40px}
body.edit .g{opacity:1!important;transform:none!important;cursor:move;outline:2px dashed rgba(250,204,21,.55);outline-offset:3px}
body.edit .g.sel{outline:2px solid #facc15}
body.edit #banners .banner{opacity:1;transform:none}
.glabel{position:absolute;left:0;top:calc(var(--u)*-2.6);padding:2px 8px;border-radius:4px;background:#facc15;color:#111;
font:600 12px "Segoe UI",sans-serif;white-space:nowrap;pointer-events:none;display:none}
body.edit .glabel{display:block}
.guide{position:fixed;background:#22d3ee;z-index:9;display:none;pointer-events:none}
#guideX{top:0;bottom:0;width:1px}#guideY{left:0;right:0;height:1px}
#toolbar{position:fixed;left:50%;bottom:12px;transform:translateX(-50%);display:none;align-items:center;gap:8px;padding:8px 12px;
border-radius:10px;background:rgba(15,17,23,.96);box-shadow:0 4px 24px rgba(0,0,0,.6);font:500 13px "Segoe UI",sans-serif;z-index:10}
body.edit #toolbar{display:flex}
#toolbar button,#toolbar select{font:600 13px "Segoe UI",sans-serif;padding:6px 14px;border-radius:6px;border:1px solid #3a4150;background:#262b36;color:#fff;cursor:pointer}
#toolbar button.main{background:#e5383b;border-color:#e5383b}
#toolbar span{color:#aab2c0;max-width:460px}
#toolbar b{color:#facc15;font-weight:600;min-width:150px}
#chips{position:fixed;left:50%;top:8px;transform:translateX(-50%);display:none;flex-wrap:wrap;justify-content:center;gap:6px;
max-width:96vw;padding:6px 10px;border-radius:10px;background:rgba(15,17,23,.92);z-index:10}
body.edit #chips{display:flex}
body.edit.bare #chips,body.edit.bare #toolbar{display:none}
#chips button{font:600 12px "Segoe UI",sans-serif;padding:3px 10px;border-radius:12px;border:1px solid #facc15;background:#facc15;color:#111;cursor:pointer}
#chips button.off{background:transparent;color:#aab2c0;border-color:#3a4150}
</style></head><body>
<div id="tower" class="g panel"><header class="accentbg"><div id="towerTitle"></div><div id="towerSub"></div></header><div id="towerRows"><div id="towerThumb"></div></div></div>
<div id="card" class="g panel"><div id="cardPlace"><b id="cardPos"></b><span id="cardClass"></span></div>
<div id="cardBody"><div id="cardTop"><span id="cardNum"></span><span id="cardName"></span><img id="cardLogo" alt=""></div>
<div id="cardTeam"></div><div id="cardStats"></div><div id="cardStory"></div></div><img id="cardPicture" alt=""></div>
<div id="battle" class="g panel"><header id="battleTitle"></header><div id="battleBody">
<div class="bside"><span class="bnum" id="bAheadNum"></span><span class="bname" id="bAheadName"></span><span class="bteam" id="bAheadTeam"></span></div>
<div id="battleGap"><b id="bGap"></b><span id="bTrend"></span></div>
<div class="bside right"><span class="bnum" id="bBehindNum"></span><span class="bname" id="bBehindName"></span><span class="bteam" id="bBehindTeam"></span></div>
</div></div>
<div id="train" class="g panel"><header id="trainTitle"></header><div id="trainCars"></div></div>
<div id="banners" class="g"></div>
<div id="pitradar" class="g panel"><header><span id="pitTitle"></span><span id="pitCount"></span></header><div id="pitRows"></div></div>
<div id="replay" class="g"><i></i><span id="replayText"></span></div>
<div id="clock" class="g panel"><span id="clockFlag"></span><div><div id="clockTime"></div><div id="clockLabel"></div></div><div id="weather"></div></div>
<div id="onboard" class="g panel"><div class="ob-head" id="obHead"><b id="obNum"></b><span id="obName"></span><em id="obAhead"></em></div>
<div class="ob-leds" id="obLeds"></div>
<div class="ob-main"><div class="ob-speed"><b id="obSpeed"></b><span id="obUnit"></span></div><div class="ob-gear" id="obGear"></div>
<div class="ob-pedals"><div class="ob-pedal"><i id="obThrottle" style="background:var(--gain)"></i></div><div class="ob-pedal"><i id="obBrake" style="background:var(--loss)"></i></div></div></div>
<div class="ob-energy" id="obEnergyRow"><span id="obEnergyLabel"></span><div><i id="obEnergy"></i></div></div>
</div>
<div id="quali" class="g panel"><div class="q-top" id="qTop"><span class="q-pos" id="qPos"></span><span class="q-name" id="qName"></span>
<span class="q-status" id="qStatus"></span><span class="q-time" id="qTime"></span></div>
<div class="q-bottom"><div class="q-sector" id="qS1"></div><div class="q-sector" id="qS2"></div><div class="q-sector" id="qS3"></div>
<div class="q-target"><span id="qTargetLabel"></span><b id="qDelta"></b></div></div></div>
<div id="map" class="g"><svg id="mapShade" viewBox="0 0 1000 1000" aria-hidden="true"><defs>
<filter id="mapGlow" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur in="SourceAlpha" stdDeviation="4.65" result="near"/>
<feComponentTransfer in="near" result="near"><feFuncA type="linear" slope=".85"/></feComponentTransfer>
<feGaussianBlur in="SourceAlpha" stdDeviation="12" result="far"/>
<feComponentTransfer in="far" result="far"><feFuncA type="linear" slope=".5"/></feComponentTransfer>
<feMerge><feMergeNode in="far"/><feMergeNode in="near"/></feMerge></filter></defs>
<g filter="url(#mapGlow)"><use href="#mapPit"></use><use href="#mapS1"></use><use href="#mapS2"></use><use href="#mapS3"></use></g></svg>
<svg id="mapSvg" viewBox="0 0 1000 1000"><path id="mapPit"></path><path id="mapS1" class="msector"></path>
<path id="mapS2" class="msector"></path><path id="mapS3" class="msector"></path><g id="mapCars"></g></svg></div>
<div id="grid" class="g panel board"><header class="accentbg"><b id="gridTitle"></b><em id="gridPage"></em></header><div id="gridCars"></div><div class="pagebar" id="gridBar"></div></div>
<div id="event" class="g panel board"><header class="accentbg"><b id="eventTrack"></b><span id="eventSession"></span></header>
<div id="eventBody"><img id="eventLogo" alt=""><div><div class="ev-cond" id="eventCond"></div><div class="ev-cast" id="eventCast"></div><div id="eventSchedule"></div></div></div></div>
<div id="results" class="g panel board"><header class="accentbg"><b id="resultsTitle"></b><span id="resultsSub"></span><em id="resultsPage"></em></header>
<div id="resultsRows"></div><div class="pagebar" id="resultsBar"></div></div>
<div id="champ" class="g panel board"><header class="accentbg"><b id="champTitle"></b><span id="champSub"></span><em id="champPage"></em></header>
<div id="champRows"></div><div class="pagebar" id="champBar"></div></div>
<div id="message" class="g panel"><div id="messageTitle"></div><div id="messageText"></div></div>
<div id="countdown" class="g panel"><header class="accentbg" id="countdownLabel"></header><div id="countdownTime"></div></div>
<div id="logo" class="g"><img id="logoImage" alt=""><span id="logoName"></span></div>
<div id="sponsors" class="g"></div>
<div class="guide" id="guideX"></div><div class="guide" id="guideY"></div>
<div id="chips"></div>
<div id="toolbar"><select id="tbPreset"></select><button class="main" id="tbSave"></button><button id="tbUndo"></button><button id="tbReset"></button>
<button id="tbResetAll"></button><b id="tbPlace"></b><span id="tbHint"></span></div>
"""
DIRECTOR_HTML = DIRECTOR_PAGE + DIRECTOR_SCRIPT
