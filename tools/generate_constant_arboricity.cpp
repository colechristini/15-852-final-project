#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using Edge = std::pair<int, int>;

namespace {

long long choose2(long long n) {
    return n * (n - 1) / 2;
}

long long parse_nonnegative(const char* s, const std::string& name) {
    std::string value(s);
    size_t parsed = 0;
    long long x = std::stoll(value, &parsed);
    if (parsed != value.size() || x < 0) {
        throw std::invalid_argument(name + " must be a nonnegative integer");
    }
    return x;
}

void add_clique_prefix_edges(std::vector<Edge>& edges, long long q, long long count) {
    for (int u = 0; u < q && static_cast<long long>(edges.size()) < count; ++u) {
        for (int v = u + 1; v < q && static_cast<long long>(edges.size()) < count; ++v) {
            edges.push_back({u, v});
        }
    }
}

void add_bounded_backward_edges(std::vector<Edge>& edges, long long n, long long first_vertex,
                                long long per_vertex_limit, long long target_edges) {
    for (int v = static_cast<int>(first_vertex);
         v < n && static_cast<long long>(edges.size()) < target_edges;
         ++v) {
        long long added_for_v = 0;
        for (int u = 0;
             u < v && added_for_v < per_vertex_limit &&
             static_cast<long long>(edges.size()) < target_edges;
             ++u) {
            edges.push_back({u, v});
            ++added_for_v;
        }
    }
}

std::vector<Edge> generate_edges(long long n, long long m, long long c,
                                 long long& core_edges) {
    if (n > std::numeric_limits<int>::max()) {
        throw std::invalid_argument("n is too large for int vertex labels");
    }

    if (c == 0) {
        if (m != 0) {
            throw std::invalid_argument("arboricity 0 requires m = 0");
        }
        core_edges = 0;
        return {};
    }

    if (c == 1) {
        if (n < 2 || m < 1 || m > n - 1) {
            throw std::invalid_argument("for c = 1, require n >= 2 and 1 <= m <= n - 1");
        }
        std::vector<Edge> edges;
        edges.reserve(static_cast<size_t>(m));
        edges.push_back({0, 1});
        core_edges = 1;
        add_bounded_backward_edges(edges, n, 2, 1, m);
        return edges;
    }

    const long long min_core_vertices = 2 * c - 1;
    const long long min_exact_core_edges = (c - 1) * (min_core_vertices - 1) + 1;
    if (n < min_core_vertices) {
        throw std::invalid_argument("exact arboricity c requires n >= 2c - 1 for this simple-graph generator");
    }
    if (m < min_exact_core_edges) {
        throw std::invalid_argument("m is too small for a simple graph with exact arboricity c");
    }

    const long long q1 = min_core_vertices;
    const long long max_core1 = choose2(q1);
    const long long cap1 = max_core1 + c * (n - q1);

    long long core_vertices = q1;
    if (m <= cap1) {
        core_edges = std::max(min_exact_core_edges, m - c * (n - q1));
    } else {
        const long long q2 = 2 * c;
        if (n < q2) {
            throw std::invalid_argument("m is too large for exact arboricity c on n vertices");
        }
        const long long max_core2 = choose2(q2);
        const long long cap2 = max_core2 + c * (n - q2);
        if (m > cap2) {
            throw std::invalid_argument("m is too large for this simple graph while preserving arboricity c");
        }
        core_vertices = q2;
        core_edges = m - c * (n - q2);
    }

    std::vector<Edge> edges;
    edges.reserve(static_cast<size_t>(m));
    add_clique_prefix_edges(edges, core_vertices, core_edges);
    add_bounded_backward_edges(edges, n, core_vertices, c, m);
    return edges;
}

std::vector<long long> make_batch_sizes(long long m, long long b, long long core_edges) {
    if (b < 1) {
        throw std::invalid_argument("b must be at least 1");
    }
    std::vector<long long> sizes(static_cast<size_t>(b), 0);
    if (b == 1) {
        sizes[0] = m;
        return sizes;
    }

    sizes[0] = core_edges;
    long long remaining = m - core_edges;
    long long base = remaining / (b - 1);
    long long extra = remaining % (b - 1);
    for (long long i = 1; i < b; ++i) {
        sizes[static_cast<size_t>(i)] = base + (i - 1 < extra ? 1 : 0);
    }
    return sizes;
}

void print_usage(const char* program) {
    std::cerr << "Usage: " << program << " <n> <m> <c> <b>\n"
              << "Outputs a batched insertion graph in run_graph_orientation.cpp format:\n"
              << "  n m b\n"
              << "  <insert-flag> <batch-size>  (repeated b times)\n"
              << "  <u> <v>                     (edges grouped by batch)\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc != 5) {
            print_usage(argv[0]);
            return 1;
        }

        const long long n = parse_nonnegative(argv[1], "n");
        const long long m = parse_nonnegative(argv[2], "m");
        const long long c = parse_nonnegative(argv[3], "c");
        const long long b = parse_nonnegative(argv[4], "b");

        long long core_edges = 0;
        std::vector<Edge> edges = generate_edges(n, m, c, core_edges);
        std::vector<long long> batch_sizes = make_batch_sizes(m, b, core_edges);

        std::cout << n << ' ' << m << ' ' << b << '\n';
        for (long long size : batch_sizes) {
            std::cout << 1 << ' ' << size << '\n';
        }

        size_t edge_index = 0;
        for (long long size : batch_sizes) {
            for (long long i = 0; i < size; ++i) {
                const auto [u, v] = edges[edge_index++];
                std::cout << u << ' ' << v << '\n';
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << '\n';
        return 1;
    }

    return 0;
}
