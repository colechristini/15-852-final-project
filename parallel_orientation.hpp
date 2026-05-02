#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/sequence.h>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <lib/skew_bag.hpp>
#include <atomic>
#include <list>
#include <cmath>


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
    int n, int tau, int tau_prime) {
    parlay::sequence<size_t> degrees(n, 0);
    for (auto &batch : edge_batches) {
        bool is_insert = batch.first;
        auto grouped_edges = parlay::group_by_key(batch.second);
        auto new_degrees = parlay::map(grouped_edges, [&](const auto& p) {
            return degrees[p.first] + p.second.size();
        });
        
        if (is_insert) {
            // insert new edges into bags
            auto new_high = parlay::filter(grouped_edges, [&](const auto& p) {
                     return new_degrees[p.first] > tau && degrees[p.first] <= tau;
            });
            // delete from V_low and add to V_high
            // get edges from edge bags of high vertices
            // run static orientation on those edges to get new orientations
            // group by vertex, construct new edge bags
            // update degrees
        }
        else {
            // delete edges from bags
            auto new_low = parlay::filter(grouped_edges, [&](const auto& p) {
                     return new_degrees[p.first] <= tau && degrees[p.first] > tau;
            });
            // delete from V_high and add to V_low
            parlay::parallel_for(0, grouped_edges.size(), [&](size_t i) {
                auto& v = grouped_edges[i].first;
                degrees[v] = new_degrees[i];;
            });
        }
    }
    graph oriented_graph(n);
    // construct oriented graph from edge bags
    return oriented_graph;
}




