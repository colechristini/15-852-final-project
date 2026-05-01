#include <lib/parlaylib/include/parlay/sequence.h>
#include <parlaylib/include/parlay/primitives.h>
#include "lib/orientation_types.hpp"

graph make_undirected_from_batches(const parlay::sequence<edge_batch>& edge_batches, int n) {
    graph undirected_graph(n);
    for (const auto& batch : edge_batches) {
        for (const auto& e : batch.second) {
            auto [u, v] = e;
            undirected_graph[u].push_back(v);
            undirected_graph[v].push_back(u);
        }
    }
    return undirected_graph;
}


int compute_approximate_arboricity(graph g) {
    int max_removed_degree = 0;
    while (g.size() > 0) {
        parlay::sequence<std::pair<size_t, size_t>> degrees = parlay::tabulate(g.size(), [&](size_t i) { return std::make_pair(g[i].size(), i); });
        auto [min_degree, min_degree_vertex] = parlay::reduce(degrees, parlay::maxm<std::pair<size_t, size_t>>());
        if (min_degree > max_removed_degree) {
            max_removed_degree = min_degree;
        }
        g = parlay::map(g, [&](const parlay::sequence<int>& neighbors) {
            parlay::sequence<int> new_neighbors;
            for (auto v : neighbors) {
                if (v != min_degree_vertex) {
                    new_neighbors.push_back(v);
                }
            }
            return new_neighbors;
        });
        g.erase(g.begin() + min_degree_vertex);
    }
    return (max_removed_degree + 1) / 2;
}


