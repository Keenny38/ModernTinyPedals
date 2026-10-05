# Race Calculator

The **Race Calculator** plans fuel, virtual energy and tyres of a race on one page: pit stop plan lap by lap, safety car and rain scenarios, several drivers, strategy comparison, and a live plan that follows the race. It replaces the former Fuel Calculator and Tyre Strategy Planner.

Open it with the `Race` entry of the navigation bar, or `Tools` > `Race Calculator`.

![Race calculator: safety car, 2 drivers, strategy and pit stop plan](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator.png)

## Page layout

- **Top bar**: data source (live session or file), `Follow Live`, `Live Race` and its status, `Undo` / `Redo`, `Race Plan` menu, `Load Live`, `Load File`, `Reset to Zero`.
- **Race setup, key figures and strategy** (shared by all tabs): race type and length, formation laps, pit stop time and safety margin; race fuel and energy, pit stops and what limits the stints, longest stint, average refill per stop, tyres used; then the strategy timeline with the fuel in the tank over the race.
- **Tabs**: `Fuel` (inputs, pit stop plan, details, scenarios, consumption history), `Tyres` (tyre wear, rules, tyre plan and stock), `Team` (LMU team stints). The page reopens on the last tab.

The inputs of the `Fuel` and `Tyres` tabs are grouped in sections: click a section title to fold it (it stays folded next time, its main values shown in the title). The `Safety Car` and `Rain` sections have their switch in the title. On a narrow window the key figures go on two rows and the consumption history below the plan.

A typed value is applied when you press `Enter` or leave the field (not at every key); everything is calculated again at once. `Up` / `Down` (or the mouse wheel once the field is selected) change the value by one step, `Shift` by ten steps, `Esc` cancels what you typed. The lap time is typed in one field: `1:59.950`, or seconds (`95.5`). Inputs and the tyre plan are kept for next time. Fuel is shown in the unit of `Config` > `Units` (`L` or `gal`), virtual energy in `%`.

## Fill in the data

- `Load Live` fills lap time and consumption with the average of the last 5 valid laps at race pace of the live session (in and out laps left out), and the race length of a live race. With LMU, before any valid lap, the game's own fuel and energy estimate is used.
- `Load File` reads a consumption history file (`.consumption` or `.csv`).
- `Follow Live` updates the inputs at each new lap of the live session.
- `History` (next to the tabs) shows the consumption history beside the plan (below on a narrow window): lap time, fuel, energy, battery, tyre wear per lap. Click a column title to sort (again: other way), `Valid Laps Only`, optional columns. Select laps (`Ctrl` + click, `Shift` + click, `Ctrl+A`) and `Add Selected Data` puts their average in the calculator (double click: one lap). `Delete Selected` (or `Delete`) and `Delete All` remove laps from the history.

## Race setup

- Race type `Time` or `Laps`, duration, formation or rolling start laps, pit stop time (time lost in the pit lane), safety margin (in laps, fuel or %).
- **Lap and consumption**: lap time, fuel and energy per lap, tank capacity. A car using energy only is planned on energy.
- **Start**: starting fuel and energy (`0` = full tank), start time of day (pit stops then shown at their time of day).
- **Pit stop**: refuel and energy rates (a splash costs less time than a full tank), driver change time, `Tyres Changed While Refuelling`, in and out lap consumption.
- **Race rules**: mandatory stops, maximum stint time, `Balanced Stints` (no short splash stint at the end), `Leader Finishes First (+1 Lap)` for time races.
- **Pace**: fuel effect on lap time, track evolution, saving cost. `Estimate from History` fills them from your consumption history.

## Drivers

With 2 drivers or more, set the stints per driver and, for each driver, the lap time difference and the minimum and maximum total driving time. The `Driving Time` card shows stints and time of each driver, with limits not met in red.

## Scenarios

- `Safety Car Scenario`: a safety car (or full course yellow) period from a lap, for some laps, with consumption, lap time and tyre wear in % of race pace, and optionally a stop under safety car.
- `Rain Scenario`: a wet period with its consumption and lap time, and optionally `Wet Tyres` (stop for wets, then for slicks).

Both are compared with the plan without the scenario, and shown on the strategy timeline.

## Strategy and pit stop plan

- **Strategy**: a timeline with one block per stint (one color per driver), pit laps above (orange when tyres are changed), safety car and rain laps behind, and the **fuel in the tank** over the race below. Hover a stint or stop for details.
- **Pit Stop Plan**: each stop with its lap, **pit window** (earliest and latest lap with the same number of stops), time, fuel and energy to add, tyres, driver and stop duration. `Export`: `Copy as Text`, `Copy for Discord`, `Export CSV...`, `Save Image...`, `Copy Picture` (strategy and plan drawn at the same size whatever the window size).
- **Details**: totals, laps a full tank lasts, what is left at stint end, consumption needed to save one stop.
- **Saving target**: laps per stint and consumption per lap needed for one stop less, with the time lost to saving and whether it is worth it.
- **Strategy Comparison**: the current plan against plans with up to 2 stops less (fuel saving) and one stop more: consumption, lap time lost, time in the pits, race time and gap. The best one is in bold.

## Live race

During a race, turn on `Live Race`: the plan for the rest of the race is recalculated at each lap and each stop from the car (laps and time done, fuel, energy, tyres, stops done). The timeline and pit stop plan start at the current lap.

- `Plan against Race` compares stints driven with the plan (laps, lap time, consumption, tyre wear), with the driver of each stint.
- `Class Rivals` lists the cars of your class: laps, stops, laps since their last stop and their next expected stop.

## Tyres tab

- **Tyre wear**: starting tread, wear per lap, measured compound, minimum tread. `Laps per Tyre Set` and `Stints Cut by Tyre Life` limit stints to what the tyres last.
- **Tyre rules**: maximum tyres for the race (`From Game` reads the LMU allocation of the session), tyre change time by number of tyres, restricted allocation (LMU rule).
- **Tyre plan**: one row per stint, the tyre on each wheel with its tread at the start and end of the stint (bar and text in the tread color, tyres used before shown dimmed when `Highlight New Tyre` is on). Drag a tyre from the stock onto a wheel, or click a wheel to pick a tyre of the stock or take it off (`Delete` on a selected wheel too). The `...` button of a row clears it, and without a strategy duplicates, inserts or deletes rows. `Propose Changes` fills the plan wheel by wheel at the stint where tread would go below the minimum, within the tyres allowed.
- **Tyre stock**: pick a compound (colored dot), add tyres (`+`), set compound options (gear button), sort by compound or by stints, remove unused tyres or all tyres. Each tyre shows the stints it runs.
- The tyre plan (`File` menu) can be saved as a `.tyre-strategy` file or exported as CSV. `Ctrl+Z` / `Ctrl+Y` undo and redo.

![Race calculator: tyre plan and stock](https://raw.githubusercontent.com/Keenny38/ModernTinyPedals/master/docs/changelog/0.20.0-race-calculator-tyres.png)

## Team tab (LMU)

Reads the stints of every driver of your car from the game, teammates included: laps, fuel, virtual energy and tyre wear per lap. It refreshes every 15 seconds while shown (`Refresh` asks at once). `Fill In Calculator` copies the average of the selected stints into the inputs, with the tank capacity of the car.

## Save and share a plan

The `Race Plan` menu:

- `Save Race Plan As...` / `Open Race Plan...`: race setup, every input and the tyre plan in one `.race-plan` file, to keep or share with your team.
- `Save for Current Car & Track` and `Open Plan of Car & Track Automatically`: the plan comes back when you drive that car on that track.
- `Copy Share Code` / `Paste Share Code...`: the whole plan as one line of text to paste in a chat. Share codes keep the fuel unit.
- `Undo` / `Redo` (`Ctrl+Z` / `Ctrl+Y`) for inputs and tyre plan.

## Race Plan overlay

Turn on the **Race Plan** overlay (`Overlays` page) to see the next stop of your plan while driving:

- lap of the next stop and laps left (highlighted when close), fuel and energy to add, tyres to change, stops left;
- distance to the pit entry and the target consumption per lap to reach the next stop (LMU);
- a check of the game pit menu against the plan: for example `80>60L` in red when the refuel set in the game differs from the plan.

The overlay uses the last inputs of the calculator, even when the calculator page is closed, and is replanned at each lap during a race.

All options: [Race calculator](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#race-calculator) and [Race plan](https://github.com/Keenny38/ModernTinyPedals/blob/master/docs/customization.md#race-plan).
