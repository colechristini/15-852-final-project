#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple


THREADS = (1, 2, 4, 8)
BATCHES = (1, 10, 100)
HIGH_ARBORICITY_CASES = (
    (13, 10_000),
    (17, 100_000),
    (20, 1_000_000),
)
LOW_ARBORICITY_CASES = (
    (3, 10_000),
    (4, 100_000),
    (4, 1_000_000),
)


def require_matplotlib() -> None:
    try:
        import matplotlib  # noqa: F401
    except ImportError as exc:
        raise SystemExit("Missing Python package: matplotlib") from exc


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate selected-speedup plots from selected_speedups.json using "
            "1-thread time / N-thread time."
        )
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=root / "benchmark_results" / "selected_speedups" / "selected_speedups.json",
        help="Input JSON produced by benchmark_selected_speedups.py.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root / "benchmark_results" / "selected_speedups_replotted",
    )
    parser.add_argument("--threads", type=int, nargs="+", default=list(THREADS))
    parser.add_argument("--batches", type=int, nargs="+", default=list(BATCHES))
    return parser.parse_args()


def load_results(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Input JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def recompute_speedups(summaries: Dict[str, Any], threads: List[int]) -> Dict[str, Any]:
    updated = json.loads(json.dumps(summaries))
    for summary in updated.values():
        one_thread = summary["threads"].get("1", {}).get("mean_time_seconds")
        for thread_count in threads:
            thread_data = summary["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            current = thread_data["mean_time_seconds"]
            thread_data["speedup_1_thread_over_n_threads"] = (
                one_thread / current if one_thread and current > 0 else float("nan")
            )
    return updated


def series_for_case(
    summaries: Dict[str, Any],
    arboricity: int,
    n: int,
    batches: List[int],
    threads: List[int],
) -> List[Tuple[int, List[int], List[float]]]:
    series = []
    for batch_count in batches:
        key = f"c{arboricity}_n{n}_b{batch_count}"
        if key not in summaries:
            continue
        xs = []
        ys = []
        for thread_count in threads:
            thread_data = summaries[key]["threads"].get(str(thread_count))
            if thread_data is None:
                continue
            xs.append(thread_count)
            ys.append(thread_data["speedup_1_thread_over_n_threads"])
        if xs:
            series.append((batch_count, xs, ys))
    return series


def plot_case(
    summaries: Dict[str, Any],
    arboricity: int,
    n: int,
    batches: List[int],
    threads: List[int],
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    plt.figure(figsize=(7.2, 4.8))
    for batch_count, xs, ys in series_for_case(summaries, arboricity, n, batches, threads):
        plt.plot(xs, ys, marker="o", label=f"{batch_count} batch{'es' if batch_count != 1 else ''}")
    plt.title(f"Parallel Speedup, c={arboricity}, n={n}")
    plt.xlabel("Threads")
    plt.ylabel("1-thread time / N-thread time")
    plt.xticks(threads)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def plot_group(
    summaries: Dict[str, Any],
    cases: Tuple[Tuple[int, int], ...],
    batches: List[int],
    threads: List[int],
    title: str,
    output_path: Path,
) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(cases), figsize=(5.3 * len(cases), 4.6), sharey=True)
    if len(cases) == 1:
        axes = [axes]

    for ax, (arboricity, n) in zip(axes, cases):
        for batch_count, xs, ys in series_for_case(summaries, arboricity, n, batches, threads):
            ax.plot(xs, ys, marker="o", label=f"{batch_count} batch{'es' if batch_count != 1 else ''}")
        ax.set_title(f"c={arboricity}, n={n}")
        ax.set_xlabel("Threads")
        ax.set_xticks(threads)
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("1-thread time / N-thread time")
    handles, labels = axes[-1].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=max(1, len(labels)))
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / ".matplotlib").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(args.output_dir / ".matplotlib"))
    require_matplotlib()

    results = load_results(args.json)
    summaries = recompute_speedups(results["summaries"], args.threads)

    written = []
    for arboricity, n in HIGH_ARBORICITY_CASES + LOW_ARBORICITY_CASES:
        output_path = args.output_dir / f"c{arboricity}_n{n}_speedup.png"
        plot_case(summaries, arboricity, n, args.batches, args.threads, output_path)
        written.append(output_path)

    high_plot = args.output_dir / "high_arboricity_speedup.png"
    low_plot = args.output_dir / "low_arboricity_speedup.png"
    plot_group(
        summaries,
        HIGH_ARBORICITY_CASES,
        args.batches,
        args.threads,
        "O(log n) Arboricity Parallel Speedup",
        high_plot,
    )
    plot_group(
        summaries,
        LOW_ARBORICITY_CASES,
        args.batches,
        args.threads,
        "O(log log n) Arboricity Parallel Speedup",
        low_plot,
    )
    written.extend([high_plot, low_plot])

    replotted_json = args.output_dir / "selected_speedups_1_over_n.json"
    output = dict(results)
    output["summaries"] = summaries
    output["replot_source_json"] = str(args.json)
    output["speedup_definition"] = "1-thread time / N-thread time"
    replotted_json.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote JSON results to {replotted_json}")
    for path in written:
        print(f"Wrote plot to {path}")


if __name__ == "__main__":
    main()
