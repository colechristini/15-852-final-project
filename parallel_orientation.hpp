#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/sequence.h>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <lib/skew_bag.hpp>
#include <atomic>
#include <list>
#include <cmath>
#include <algorithm>
#include <vector>

namespace {

bool sequence_contains(const parlay::sequence<vertex>& neighbors, vertex v) {
    return std::find(neighbors.begin(), neighbors.end(), v) != neighbors.end();
}

parlay::sequence<edge> outgoing_edges_for_vertices(
        const parlay::sequence<skew_bag<vertex>>& edge_bags,
        const parlay::sequence<vertex>& vertices) {
    auto degrees = parlay::tabulate(vertices.size(), [&](size_t i) {
        return edge_bags[vertices[i]].size();
    });
    auto offsets_and_total = parlay::scan(degrees);
    const auto& offsets = offsets_and_total.first;
    size_t total = offsets_and_total.second;

    parlay::sequence<edge> edges(total);
    parlay::parallel_for(0, vertices.size(), [&](size_t i) {
        vertex u = vertices[i];
        auto neighbors = edge_bags[u].to_sequence();
        for (size_t j = 0; j < neighbors.size(); j++) {
            edges[offsets[i] + j] = {u, neighbors[j]};
        }
    });
    return edges;
}

void recompute_degrees_and_levels(
        const parlay::sequence<skew_bag<vertex>>& edge_bags,
        parlay::sequence<size_t>& degrees,
        parlay::sequence<unsigned char>& in_vhigh,
        int tau) {
    parlay::parallel_for(0, edge_bags.size(), [&](size_t i) {
        degrees[i] = edge_bags[i].size();
        in_vhigh[i] = degrees[i] > static_cast<size_t>(tau);
    });
}

}


graph static_orientation(const parlay::sequence<std::pair<vertex, vertex>>& edges,
                         int c, double epsilon,
                         int n) {
    auto normalized_edges = parlay::map(edges, [](const auto& p) {
        auto [u, v] = p;
        if (u < v) return std::make_pair(u, v);
        else return std::make_pair(v, u);
    });

    auto non_self_edges = parlay::filter(normalized_edges, [](const auto& e) {
        return e.first != e.second;
    });
    auto undirected_edges = parlay::remove_duplicates_ordered(non_self_edges);

    auto active_edges = parlay::tabulate(2 * undirected_edges.size(), [&](size_t i) {
        auto [u, v] = undirected_edges[i / 2];
        return (i % 2 == 0) ? std::make_pair(u, v) : std::make_pair(v, u);
    });

    parlay::sequence<edge> oriented_edges;
    const double degree_threshold = (2.0 + epsilon) * static_cast<double>(c);

    while (!active_edges.empty()) {
        auto grouped_edges = parlay::group_by_key(active_edges);
        parlay::sequence<unsigned char> vertex_marked(n, 0);

        parlay::parallel_for(0, grouped_edges.size(), [&](size_t i) {
            vertex u = grouped_edges[i].first;
            if (grouped_edges[i].second.size() <= degree_threshold) {
                vertex_marked[u] = 1;
            }
        });

        if (parlay::count(vertex_marked, static_cast<unsigned char>(1)) == 0) {
            auto min_degree_vertex = parlay::min_element(
                grouped_edges,
                [](const auto& a, const auto& b) {
                    return a.second.size() < b.second.size();
                });
            vertex_marked[min_degree_vertex->first] = 1;
        }

        auto newly_oriented = parlay::filter(active_edges, [&](const auto& e) {
            auto [u, v] = e;
            return vertex_marked[u] &&
                   (!vertex_marked[v] || (vertex_marked[v] && u < v));
        });
        oriented_edges = parlay::append(oriented_edges, newly_oriented);

        active_edges = parlay::filter(active_edges, [&](const auto& e) {
            auto [u, v] = e;
            return !vertex_marked[u] && !vertex_marked[v];
        });
    }

    graph oriented_graph(n);
    auto grouped_oriented_edges = parlay::group_by_key(oriented_edges);
    parlay::parallel_for(0, grouped_oriented_edges.size(), [&](size_t i) {
        vertex u = grouped_oriented_edges[i].first;
        oriented_graph[u] = grouped_oriented_edges[i].second;
    });
    return oriented_graph;
}

graph parallel_amortized_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int c, double epsilon) {
    double c_doub = static_cast<double>(c);
    int tau = static_cast<int>(std::round((24. / 5.) * c_doub));
    parlay::sequence<skew_bag<vertex>> edge_bags(n);
    parlay::sequence<size_t> degrees(n, 0);
    parlay::sequence<unsigned char> in_vhigh(n, 0);

    for (auto &batch : edge_batches) {
        bool is_insert = batch.first;
        if (is_insert) {
            // Arbitrarily orient the batch as given and add those edges to the graph.
            auto grouped_edges = parlay::group_by_key(batch.second);
            parlay::parallel_for(0, grouped_edges.size(), [&](size_t i) {
                vertex u = grouped_edges[i].first;
                edge_bags[u].batch_insert(grouped_edges[i].second);
            });
            recompute_degrees_and_levels(edge_bags, degrees, in_vhigh, tau);
            auto vhigh = parlay::filter(parlay::tabulate(n, [](size_t i) {
                return static_cast<vertex>(i);
            }), [&](vertex u) {
                return in_vhigh[u];
            });
            auto high_out_edges = outgoing_edges_for_vertices(edge_bags, vhigh);
            if (!high_out_edges.empty()) {
                parlay::parallel_for(0, vhigh.size(), [&](size_t i) {
                    edge_bags[vhigh[i]] = skew_bag<vertex>();
                });
                graph statically_oriented = static_orientation(high_out_edges, c, epsilon, n);
                parlay::parallel_for(0, statically_oriented.size(), [&](size_t u) {
                    if (!statically_oriented[u].empty()) {
                        edge_bags[u].batch_insert(statically_oriented[u]);
                    }
                });
                recompute_degrees_and_levels(edge_bags, degrees, in_vhigh, tau);
            }
        }
        else {
            auto with_reversed_edges = parlay::map(batch.second, [](const auto& e) {
                auto [u, v] = e;
                return std::make_pair(v, u);
            });
            auto grouped_forward_edges = parlay::group_by_key(batch.second);
            auto grouped_reversed_edges = parlay::group_by_key(with_reversed_edges);
            parlay::parallel_for(0, grouped_forward_edges.size(), [&](size_t i) {
                vertex u = grouped_forward_edges[i].first;
                auto neighbors = grouped_forward_edges[i].second;
                edge_bags[u].batch_delete(neighbors);
            });
            parlay::parallel_for(0, grouped_reversed_edges.size(), [&](size_t i) {
                vertex v = grouped_reversed_edges[i].first;
                auto neighbors = grouped_reversed_edges[i].second;
                edge_bags[v].batch_delete(neighbors);
            });
            recompute_degrees_and_levels(edge_bags, degrees, in_vhigh, tau);
        }
    }

    graph oriented_graph(n);
    parlay::parallel_for(0, edge_bags.size(), [&](size_t u) {
        oriented_graph[u] = edge_bags[u].to_sequence();
    });
    return oriented_graph;
}
