"""Equipment dashboard as an image: one page per Excel record, for the viewer's Dashboard button.

    python -m app.dashboard OUT_DIR [--workbook PACK.xlsx] [--tags P-005 FV-101]

Shows the record's health, 3-day telemetry for its kind of equipment, two weeks of events, its
maintenance history, and known data problems. Everything comes from the synthetic builder pack.
The header says how the 3D object was linked to the record, because most links are made by rule.
"""

from __future__ import annotations

import argparse
import io
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle, Wedge  # noqa: E402

from app.copilot.store import DataStore  # noqa: E402

BG = "#11161c"
PANEL = "#1a212b"
GRID = "#2a3340"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
ACCENT = "#22d3ee"
WARN = "#f59e0b"
SEVERITY = {"high": "#ff4d4f", "medium": "#f59e0b", "low": "#38bdf8"}
WORK = {
    "corrective": "#ff4d4f",
    "predictive": "#a78bfa",
    "preventive": "#22c55e",
    "inspection": "#38bdf8",
}
LINES = ["#22d3ee", "#f59e0b"]

# What to plot for each kind of equipment: (title, unit, metrics). Two metrics share a panel.
SIGNALS = {
    "PROCESS_PUMP": [
        ("Motor current", "A", ["motor_current_a"]),
        ("Bearing temperature", "°C", ["bearing_temp_c"]),
        ("Vibration", "mm/s", ["vibration_mm_s"]),
        ("Flow", "%", ["process_flow_pct"]),
    ],
    "ELECTRIC_MOTOR": [
        ("Motor current", "A", ["motor_current_a"]),
        ("Bearing temperature", "°C", ["bearing_temp_c"]),
        ("Vibration", "mm/s", ["vibration_mm_s"]),
        ("Speed", "rpm", ["speed_rpm"]),
    ],
    "CONTROL_VALVE": [
        ("Position", "%", ["position_setpoint_pct", "position_actual_pct"]),
        ("Stiction index", "", ["stiction_index"]),
        ("Air supply", "bar", ["pneumatic_supply_bar"]),
        ("Flow", "%", ["process_flow_pct"]),
    ],
    "PRESSURE_TRANSMITTER": [
        ("Process pressure", "bar", ["process_pressure_bar"]),
        ("Sensor bias", "", ["sensor_bias"]),
        ("Signal quality", "%", ["signal_quality_pct"]),
    ],
    "VIBRATION_SENSOR": [
        ("Vibration", "mm/s", ["vibration_mm_s"]),
        ("Sensor bias", "", ["sensor_bias"]),
        ("Signal quality", "%", ["signal_quality_pct"]),
    ],
}
LEGEND_NAMES = {"position_setpoint_pct": "setpoint", "position_actual_pct": "actual"}


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", ""))
    except ValueError:
        return None


def health_color(score: float) -> str:
    return "#22c55e" if score >= 80 else WARN if score >= 60 else "#ff4d4f"


def style(ax, title: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_title(title, color=TEXT, fontsize=11, loc="left", pad=6, fontweight="bold")
    ax.tick_params(colors=MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def legend(ax, handles=None, **kwargs) -> None:
    ax.legend(
        handles=handles, fontsize=8, facecolor=PANEL, edgecolor=GRID, labelcolor=TEXT, **kwargs
    )


def trend_note(values: list[float]) -> str:
    """Mean of the first 12 hours against the last 12, at one reading every 30 minutes."""
    if len(values) < 48:
        return ""
    before, after = sum(values[:24]) / 24, sum(values[-24:]) / 24
    if abs(after - before) < 1e-9:
        return "flat"
    share = f" ({(after - before) / abs(before):+.0%})" if abs(before) > 1e-6 else ""
    return f"first 12 h {number(before)} → last 12 h {number(after)}{share}"


def number(value: float) -> str:
    return f"{value:.0f}" if abs(value) >= 100 else f"{value:.3g}"


def link_note(mapping: dict | None) -> tuple[str, str]:
    """How the 3D object was tied to this record, in a warning colour unless it's confirmed."""
    if not mapping:
        return "Record shown on its own, not through a 3D object", MUTED
    method = mapping.get("method") or "unknown method"
    text = f"3D object {mapping.get('object_id', '?')} linked by {method.replace('_', ' ')}"
    if mapping.get("confidence") is not None:
        text += f", confidence {mapping['confidence']}"
    confirmed = not method.startswith("procedural") and "unconfirmed" not in method
    if not confirmed:
        text += ". Not a confirmed identity: check the tag on site."
    return text, ACCENT if confirmed else WARN


def draw_gauge(ax, score: float | None, state: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-0.62, 1.15)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.add_patch(Wedge((0, 0), 1, 0, 180, width=0.24, color=GRID))
    if score is None:
        ax.text(0, 0.2, "?", ha="center", va="center", color=MUTED, fontsize=30)
        ax.text(0, -0.42, "no condition record", ha="center", color=MUTED, fontsize=11)
        return
    angle = 180 * max(0.0, min(score, 100.0)) / 100
    ax.add_patch(Wedge((0, 0), 1, 180 - angle, 180, width=0.24, color=health_color(score)))
    ax.text(
        0, 0.2, f"{score:.0f}", ha="center", va="center", color=TEXT, fontsize=30, weight="bold"
    )
    ax.text(0, -0.12, "health / 100", ha="center", color=MUTED, fontsize=9)
    ax.text(0, -0.45, state.replace("_", " "), ha="center", color=health_color(score), fontsize=12)


def draw_facts(ax, title: str, rows: list[tuple], width: int) -> None:
    """Rows are (name, value) or (name, value, colour)."""
    ax.set_facecolor(PANEL)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.text(
        0.03, 0.92, title, color=TEXT, fontsize=11, weight="bold", va="top", transform=ax.transAxes
    )
    y = 0.74
    for key, value, *colour in rows:
        text = value if len(value) <= width else value[: width - 1] + "…"
        ax.text(0.03, y, key, color=MUTED, fontsize=9.5, va="top", transform=ax.transAxes)
        ax.text(
            0.33,
            y,
            text,
            color=colour[0] if colour else TEXT,
            fontsize=9.5,
            va="top",
            transform=ax.transAxes,
        )
        y -= 0.15


def draw_signal(ax, title: str, unit: str, metrics: list[str], times, telemetry) -> None:
    style(ax, title + (f"  [{unit}]" if unit else ""))
    note = ""
    for color, metric in zip(LINES, metrics, strict=False):
        pairs = [
            (t, p.metrics[metric])
            for t, p in zip(times, telemetry, strict=True)
            if metric in p.metrics
        ]
        if not pairs:
            continue
        xs, ys = zip(*pairs, strict=True)
        ax.plot(xs, ys, color=color, linewidth=1.6, label=LEGEND_NAMES.get(metric, metric))
        if len(metrics) == 1:
            ax.fill_between(xs, ys, min(ys), color=color, alpha=0.10)
            note = trend_note(list(ys))
    if not ax.lines:
        ax.text(
            0.5, 0.5, "no readings", ha="center", va="center", color=MUTED, transform=ax.transAxes
        )
        return
    if len(ax.lines) > 1:
        legend(ax, loc="lower left")
    if note:
        ax.text(
            0.99,
            0.03,
            note,
            ha="right",
            va="bottom",
            color=MUTED,
            fontsize=7.5,
            transform=ax.transAxes,
        )
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.margins(x=0.01, y=0.15)


def draw_events(ax, events) -> None:
    open_count = sum(e.status.lower() == "open" for e in events)
    style(ax, f"Alarms and events  ({len(events)}, {open_count} open)")
    kinds = sorted({e.event_type for e in events})
    for event in events:
        when = parse_time(event.timestamp)
        if when is None:
            continue
        color = SEVERITY.get(event.severity.lower(), MUTED)
        is_open = event.status.lower() == "open"
        ax.scatter(
            when,
            kinds.index(event.event_type),
            s=80 if is_open else 45,
            facecolor=color if is_open else "none",
            edgecolor=color,
            linewidth=1.6,
            zorder=3,
        )
    if not kinds:
        ax.text(
            0.5, 0.5, "no events", ha="center", va="center", color=MUTED, transform=ax.transAxes
        )
        return
    ax.set_yticks(range(len(kinds)))
    ax.set_yticklabels([k.replace("_", " ").lower() for k in kinds], color=TEXT, fontsize=8)
    ax.set_ylim(-0.7, len(kinds) - 0.3)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=c, label=s) for s, c in SEVERITY.items()
    ]
    handles.append(
        plt.Line2D(
            [],
            [],
            marker="o",
            linestyle="",
            markerfacecolor=MUTED,
            color=MUTED,
            label="filled: open",
        )
    )
    legend(ax, handles, loc="lower right", ncol=4, bbox_to_anchor=(1, 1.01), borderaxespad=0)
    # Room on the left for the event names.
    box = ax.get_position()
    ax.set_position([box.x0 + 0.06, box.y0, box.width - 0.06, box.height])


def draw_quality(ax, quality) -> None:
    ax.set_facecolor(PANEL)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.text(
        0.04,
        0.92,
        f"Data problems  ({len(quality)})",
        color=TEXT,
        fontsize=11,
        weight="bold",
        va="top",
        transform=ax.transAxes,
    )
    counts = Counter(issue.issue_type.replace("_", " ") for issue in quality)
    for row, (kind, count) in enumerate(counts.most_common(6)):
        ax.text(
            0.04,
            0.74 - row * 0.13,
            f"{count}×",
            color=WARN,
            fontsize=10,
            va="top",
            transform=ax.transAxes,
        )
        ax.text(
            0.16,
            0.74 - row * 0.13,
            kind,
            color=TEXT,
            fontsize=9.5,
            va="top",
            transform=ax.transAxes,
        )
    if not counts:
        ax.text(
            0.04, 0.74, "none recorded", color=MUTED, fontsize=9.5, va="top", transform=ax.transAxes
        )


def draw_maintenance(ax, orders, due: datetime | None, now: datetime | None) -> None:
    downtime = sum(o.downtime_h for o in orders)
    style(ax, f"Maintenance history  ({len(orders)} work orders, {downtime:.1f} h downtime)")
    for order in orders:
        when = parse_time(order.opened_at)
        if when is None:
            continue
        color = WORK.get(order.maintenance_type.lower(), MUTED)
        ax.bar(when, order.duration_h, width=8, color=color)
        if order.downtime_h:
            ax.bar(
                when,
                min(order.downtime_h, order.duration_h),
                width=8,
                color="none",
                edgecolor=TEXT,
                hatch="////",
                linewidth=0,
            )
    dates = [d for d in (parse_time(o.opened_at) for o in orders) if d]
    if not dates:
        ax.text(
            0.5,
            0.5,
            "no work orders",
            ha="center",
            va="center",
            color=MUTED,
            transform=ax.transAxes,
        )
    else:
        start, end = min(dates) - timedelta(days=30), max(dates) + timedelta(days=60)
        if now:
            end = max(end, now + timedelta(days=20))
            ax.axvline(now, color=MUTED, linewidth=1)
            ax.annotate(
                f"data as of {now:%d %b %Y} ",
                (now, 0.80),
                xycoords=("data", "axes fraction"),
                color=MUTED,
                fontsize=8,
                va="top",
                ha="right",
            )
        late = bool(due and now and due < now)
        label = (
            f"{'service overdue since' if late else 'next service due'} {due:%d %b %Y}"
            if due
            else ""
        )
        colour = "#ff4d4f" if late else ACCENT
        # A due date years ahead would squash the history, so it's named instead of drawn.
        if due and due <= end + timedelta(days=120):
            end = max(end, due + timedelta(days=20))
            ax.axvline(due, color=colour, linestyle="--", linewidth=1.3)
            # A coming due date sits near the right edge, so its label goes to the left of it.
            ax.annotate(
                f" {label}" if late else f"{label} ",
                (due, 0.97),
                xycoords=("data", "axes fraction"),
                color=colour,
                fontsize=8,
                va="top",
                ha="left" if late else "right",
            )
        elif due:
            ax.text(
                0.995,
                0.95,
                f"{label} →",
                ha="right",
                va="top",
                color=colour,
                fontsize=8.5,
                transform=ax.transAxes,
            )
        ax.set_xlim(start, end)
    ax.set_ylabel("hours", color=MUTED, fontsize=8)
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    ax.margins(y=0.25)
    handles = [Rectangle((0, 0), 1, 1, color=c, label=t) for t, c in WORK.items()]
    handles.append(
        Rectangle((0, 0), 1, 1, facecolor="none", edgecolor=TEXT, hatch="////", label="downtime")
    )
    legend(ax, handles, loc="upper left", ncol=5)


def render_dashboard(store: DataStore, id_or_tag: str, mapping: dict | None = None) -> bytes:
    """Return one Excel record's dashboard as PNG bytes. Raises KeyError for an unknown record.

    `mapping` is the 3D object's link to the record, with its object_id, method and confidence.
    """
    asset = store.get_asset(id_or_tag)
    if asset is None:
        raise KeyError(id_or_tag)
    state = store.get_current_state(asset.asset_id)
    points = store.get_telemetry(asset.asset_id, limit=100_000)
    stamped = [(parse_time(p.timestamp), p) for p in points]
    stamped = [(t, p) for t, p in stamped if t is not None]
    times = [t for t, _ in stamped]
    telemetry = [p for _, p in stamped]
    events = store.get_events(asset.asset_id, limit=100_000)
    orders = store.get_maintenance(asset.asset_id)
    quality = store.get_data_quality(asset.asset_id)
    last = parse_time(asset.last_service_date)
    interval = asset.service_interval_days
    due = last + timedelta(days=interval) if last and interval else None
    # "Now" is when the data was taken, not today: the pack is a snapshot.
    stamps = [t for t in [*times, parse_time(state.last_updated) if state else None] if t]
    now = max(stamps) if stamps else None
    overdue = bool(due and now and due < now)

    fig = plt.figure(figsize=(16, 10), dpi=100, facecolor=BG)
    grid = fig.add_gridspec(
        4,
        4,
        height_ratios=[1.0, 1.05, 1.0, 0.95],
        hspace=0.62,
        wspace=0.22,
        left=0.05,
        right=0.985,
        top=0.875,
        bottom=0.045,
    )
    kind = asset.asset_class.replace("_", " ").lower()
    fig.text(0.05, 0.952, asset.tag, color=TEXT, fontsize=24, weight="bold", va="baseline")
    fig.text(
        0.05,
        0.925,
        f"{kind}  ·  {asset.area_name}  ·  criticality {asset.criticality}  ·  {asset.asset_id}",
        color=MUTED,
        fontsize=11.5,
    )
    note, color = link_note(mapping)
    fig.text(0.05, 0.897, note, color=color, fontsize=10)
    fig.text(
        0.985, 0.897, "Synthetic data, Valmet builder pack", color=MUTED, fontsize=9, ha="right"
    )

    draw_gauge(
        fig.add_subplot(grid[0, 0]),
        state.health_score if state else None,
        state.condition_state if state else "",
    )
    condition = []
    if state:
        issue = (
            f"{state.issue_code}: {state.issue_summary}"
            if state.issue_code
            else state.issue_summary
        )
        condition = [
            ("Issue", issue or "none"),
            ("Urgency", state.urgency),
            ("Next check", state.recommended_next_check or "none"),
            ("Model confidence", f"{state.model_confidence:.0%}"),
            ("Updated", state.last_updated[:16].replace("T", " ")),
        ]
    draw_facts(fig.add_subplot(grid[0, 1:3]), "Condition", condition, 70)
    service = [
        ("Installed", asset.installation_date[:10]),
        ("Last service", asset.last_service_date[:10]),
        ("Interval", f"{interval} days" if interval else "unknown"),
        (
            "Next due",
            (f"{due.date().isoformat()}" + ("  overdue" if overdue else "")) if due else "unknown",
            "#ff4d4f" if overdue else TEXT,
        ),
        ("Connectivity", asset.connectivity_profile or "unknown"),
    ]
    draw_facts(fig.add_subplot(grid[0, 3]), "Service", service, 24)

    panels = SIGNALS.get(asset.asset_class)
    if panels is None:
        found = sorted({m for p in telemetry for m in p.metrics})[:4]
        panels = [(m.replace("_", " "), "", [m]) for m in found]
    if panels:
        span = 4 // len(panels) if len(panels) in (1, 2, 4) else 1
        for column, (title, unit, metrics) in enumerate(panels[:4]):
            cell = grid[1, column * span : (column + 1) * span]
            draw_signal(fig.add_subplot(cell), title, unit, metrics, times, telemetry)
    else:
        ax = fig.add_subplot(grid[1, :])
        style(ax, "Telemetry")
        ax.text(
            0.5, 0.5, "no readings", ha="center", va="center", color=MUTED, transform=ax.transAxes
        )
    if len(panels) == 3:
        draw_quality(fig.add_subplot(grid[1, 3]), quality)

    draw_events(fig.add_subplot(grid[2, :3] if len(panels) != 3 else grid[2, :]), events)
    if len(panels) != 3:
        draw_quality(fig.add_subplot(grid[2, 3]), quality)
    draw_maintenance(fig.add_subplot(grid[3, :]), orders, due, now)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=BG)
    plt.close(fig)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--tags", nargs="*", help="default: every record")
    args = parser.parse_args()
    store = DataStore.load(args.workbook)
    args.out.mkdir(parents=True, exist_ok=True)
    tags = args.tags or [asset.tag for asset in store.list_assets()]
    for tag in tags:
        (args.out / f"{tag}.png").write_bytes(render_dashboard(store, tag))
    print(f"{len(tags)} dashboards in {args.out}")


if __name__ == "__main__":
    main()
