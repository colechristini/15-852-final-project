#!/usr/bin/env python3

import argparse
import random
import sys
from pathlib import Path
from typing import List, TextIO, Tuple


Edge = Tuple[int, int]


def choose2(n: int) -> int:
    return n * (n - 1) // 2


def min_edges_for_arboricity(n: int, c: int) -> int:
    if c == 0:
        return 0
    if c == 1:
        if n < 2:
            raise ValueError("for c = 1, require n >= 2")
        return 1

    min_core_vertices = 2 * c - 1
    if n < min_core_vertices:
        raise ValueError(
            "exact arboricity c requires n >= 2c - 1 for this simple-graph generator"
        )
    return (c - 1) * (min_core_vertices - 1) + 1


def max_edges_for_arboricity(n: int, c: int) -> int:
    if c == 0:
        return 0
    if c == 1:
        if n < 2:
            raise ValueError("for c = 1, require n >= 2")
        return n - 1

    min_core_vertices = 2 * c - 1
    if n < min_core_vertices:
        raise ValueError(
            "exact arboricity c requires n >= 2c - 1 for this simple-graph generator"
        )
    if n == min_core_vertices:
        return choose2(min_core_vertices)
    return c * (n - 1)


def default_edge_count(n: int, c: int, b: int) -> int:
    max_edges = max_edges_for_arboricity(n, c)
    m = max_edges - (max_edges % b)
    min_edges = min_edges_for_arboricity(n, c)
    if m < min_edges:
        raise ValueError(
            "no default edge count is divisible by b while preserving exact arboricity c"
        )
    return m


def add_clique_prefix_edges(edges: List[Edge], q: int, target_edges: int) -> None:
    for u in range(q):
        for v in range(u + 1, q):
            if len(edges) >= target_edges:
                return
            edges.append((u, v))


def add_bounded_backward_edges(
    edges: List[Edge],
    n: int,
    first_vertex: int,
    per_vertex_limit: int,
    target_edges: int,
) -> None:
    for v in range(first_vertex, n):
        added_for_v = 0
        for u in range(v):
            if added_for_v >= per_vertex_limit or len(edges) >= target_edges:
                break
            edges.append((u, v))
            added_for_v += 1
        if len(edges) >= target_edges:
            return


def generate_edges(n: int, m: int, c: int) -> List[Edge]:
    if c == 0:
        if m != 0:
            raise ValueError("arboricity 0 requires m = 0")
        return []

    if c == 1:
        if n < 2 or m < 1 or m > n - 1:
            raise ValueError("for c = 1, require n >= 2 and 1 <= m <= n - 1")
        edges: List[Edge] = [(0, 1)]
        add_bounded_backward_edges(edges, n, 2, 1, m)
        return edges

    min_core_vertices = 2 * c - 1
    min_exact_core_edges = (c - 1) * (min_core_vertices - 1) + 1
    if n < min_core_vertices:
        raise ValueError(
            "exact arboricity c requires n >= 2c - 1 for this simple-graph generator"
        )
    if m < min_exact_core_edges:
        raise ValueError("m is too small for a simple graph with exact arboricity c")

    q1 = min_core_vertices
    cap1 = choose2(q1) + c * (n - q1)

    if m <= cap1:
        core_vertices = q1
        core_edges = max(min_exact_core_edges, m - c * (n - q1))
    else:
        q2 = 2 * c
        if n < q2:
            raise ValueError("m is too large for exact arboricity c on n vertices")
        cap2 = choose2(q2) + c * (n - q2)
        if m > cap2:
            raise ValueError(
                "m is too large for this simple graph while preserving arboricity c"
            )
        core_vertices = q2
        core_edges = m - c * (n - q2)

    edges: List[Edge] = []
    add_clique_prefix_edges(edges, core_vertices, core_edges)
    add_bounded_backward_edges(edges, n, core_vertices, c, m)
    return edges


def randomize_edges(edges: List[Edge], n: int, seed: int) -> List[Edge]:
    rng = random.Random(seed)
    vertex_permutation = list(range(n))
    rng.shuffle(vertex_permutation)

    randomized_edges = [
        tuple(sorted((vertex_permutation[u], vertex_permutation[v]))) for u, v in edges
    ]
    rng.shuffle(randomized_edges)
    return randomized_edges


def write_batched_graph(
    n: int, m: int, b: int, edges: List[Edge], output: TextIO
) -> None:
    batch_size = m // b

    print(n, m, b, file=output)
    for _ in range(b):
        print(1, batch_size, file=output)

    edge_index = 0
    for _ in range(b):
        for _ in range(batch_size):
            u, v = edges[edge_index]
            print(u, v, file=output)
            edge_index += 1


def output_path(output_dir: Path, n: int, c: int, b: int, seed: int) -> Path:
    return output_dir / f"n{n}_c{c}_b{b}_s{seed}.txt"


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be a nonnegative integer") from e
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a simple insertion-only graph with exact final arboricity c "
            "and b equal-sized batches."
        )
    )
    parser.add_argument(
        "values",
        type=nonnegative_int,
        nargs="+",
        metavar="N",
        help=(
            "use: n c [b]. For compatibility, n m c b is also accepted when "
            "four positional values are provided."
        ),
    )
    parser.add_argument(
        "--edges",
        "-m",
        type=nonnegative_int,
        help=(
            "number of edges; defaults to the largest supported count divisible by b"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help=(
            "directory to write the generated batched graph as "
            "n[n]_c[c]_b[b]_s[s].txt"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        help=(
            "seed for reproducible random vertex relabeling and edge order; "
            "omit for deterministic output"
        ),
    )
    return parser.parse_args()


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    if len(args.values) == 2:
        args.n, args.c = args.values
        args.b = 1
    elif len(args.values) == 3:
        args.n, args.c, args.b = args.values
    elif len(args.values) == 4:
        if args.edges is not None:
            raise ValueError("do not pass both --edges and legacy positional m")
        args.n, args.edges, args.c, args.b = args.values
    else:
        raise ValueError("usage is n c [b], or legacy n m c b")

    args.m = args.edges
    del args.values
    return args


def main() -> int:
    try:
        args = normalize_args(parse_args())
        if args.b < 1:
            raise ValueError("b must be at least 1")
        if args.m is None:
            args.m = default_edge_count(args.n, args.c, args.b)
        if args.m % args.b != 0:
            raise ValueError("m must be divisible by b so each batch has m/b edges")

        edges = generate_edges(args.n, args.m, args.c)
        if args.seed is not None:
            edges = randomize_edges(edges, args.n, args.seed)

        if args.output is not None:
            if args.seed is None:
                raise ValueError("--seed is required when --output is provided")
            args.output.mkdir(parents=True, exist_ok=True)
            graph_path = output_path(args.output, args.n, args.c, args.b, args.seed)
            with graph_path.open("w", encoding="utf-8") as output:
                write_batched_graph(args.n, args.m, args.b, edges, output)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
