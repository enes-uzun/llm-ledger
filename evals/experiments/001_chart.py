"""Render the headline chart for experiment 001 from the human-audited summaries.

Usage: python evals/experiments/001_chart.py   ->  evals/experiments/001-reasoning.png
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
OUT = Path(__file__).with_name("001-reasoning.png")

SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
OFF, ON = "#2a78d6", "#eb6834"  # validated categorical slots 1-2 (light)

# (row label, reasoning-off run, reasoning-on run or None)
ROWS = [
    ("Qwen3 8B (local)", "20261011T141550Z_qwen3-8b", "20261012T060011Z_qwen3-8b_e2-think"),
    ("gpt-5-nano", "20261016T182628Z_gpt-5-nano_ref-minimal", "20261016T182801Z_gpt-5-nano_ref-medium"),
    ("gpt-5-mini", "20261016T183340Z_gpt-5-mini_ref-minimal", None),
]


def load(run: str | None) -> dict | None:
    if run is None:
        return None
    return json.loads((RESULTS / f"{run}.audited.summary.json").read_text(encoding="utf-8"))


def metrics(s: dict) -> dict:
    return {
        "risk": s["overall"]["risk_score"],
        "abstain": int(s["false_abstentions"].split("/")[0]),
        "p50": s["overall"]["latency_p50_s"],
    }


def main() -> None:
    data = [(label, metrics(load(off)), metrics(load(on)) if on else None) for label, off, on in ROWS]

    plt.rcParams.update({"font.family": ["Helvetica Neue", "DejaVu Sans"], "font.size": 10, "text.color": INK,
                         "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK})
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9), dpi=200, sharey=True,
                             gridspec_kw={"wspace": 0.08})
    fig.patch.set_facecolor(SURFACE)

    panels = [
        (axes[0], "risk", (0, 1.0), "Risk score  (higher is better)", "{:.2f}"),
        (axes[1], "abstain", (0, 24), "Unnecessary “no answer”  (of 24, lower is better)", "{:d}"),
    ]
    ys = list(range(len(data)))[::-1]
    for ax, key, xlim, xlabel, fmt in panels:
        ax.set_facecolor(SURFACE)
        span = xlim[1] - xlim[0]
        for y, (_, off, on) in zip(ys, data):
            if on:
                ax.plot([off[key], on[key]], [y, y], color=GRID, lw=2, zorder=1, solid_capstyle="round")
            pts = [(off, OFF)] + ([(on, ON)] if on else [])
            # label the left point on its left, the right point on its right
            ordered = sorted(pts, key=lambda p: p[0][key])
            for i, (m, color) in enumerate(ordered):
                ax.scatter(m[key], y, s=90, color=color, edgecolor=SURFACE, linewidth=2, zorder=3)
                left = i == 0 and len(ordered) > 1
                dx = -0.03 * span if left else 0.03 * span
                ax.annotate(fmt.format(m[key]), (m[key], y), xytext=(m[key] + dx, y),
                            ha="right" if left else "left", va="center", fontsize=9.5, color=INK_2)
        ax.set_xlim(xlim[0] - 0.08 * span, xlim[1] + 0.08 * span)
        ax.set_xlabel(xlabel, fontsize=9.5, labelpad=8)
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", length=0, labelsize=8.5)

    axes[0].set_yticks(ys)
    axes[0].set_yticklabels([d[0] for d in data], fontsize=10)
    axes[0].set_ylim(-0.6, len(data) - 0.4)

    fig.text(0.02, 0.97, "Reasoning budget mattered more than model choice", fontsize=13.5,
             fontweight="bold", va="top")
    fig.text(0.02, 0.905, "36-question Turkish finance QA with the answer passages in context, human-audited. "
             "Risk score: correct +1, partial +0.5, “no answer” 0, wrong −1.",
             fontsize=9, color=INK_2, va="top")
    handles = [Line2D([], [], marker="o", ls="", markersize=8, color=OFF, label="Reasoning off"),
               Line2D([], [], marker="o", ls="", markersize=8, color=ON, label="Reasoning on")]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.985, 0.985), ncol=2, frameon=False,
               fontsize=9.5, handletextpad=0.3, columnspacing=1.2)

    lat = "   ".join(f"{label}: {off['p50']:.1f} s" + (f" → {on['p50']:.1f} s" if on else "")
                     for label, off, on in data)
    fig.text(0.02, 0.025, f"Median latency, reasoning off → on.   {lat}", fontsize=8.5, color=MUTED)
    fig.text(0.985, 0.025, "github.com/enes-uzun/llm-ledger", fontsize=8.5, color=MUTED, ha="right")

    fig.subplots_adjust(left=0.15, right=0.985, top=0.76, bottom=0.25)
    fig.savefig(OUT, facecolor=SURFACE)
    print(f"saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
