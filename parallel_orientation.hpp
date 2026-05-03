#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/sequence.h>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <lib/skew_bag.hpp>
#include <lib/hash_bag.hpp>
#include <atomic>
#include <list>
#include <cmath>
#include <algorithm>
#include <unordered_map>
#include <unordered_set>
#include <vector>

struct ParallelEdgeHash {
    size_t operator()(const edge& e) const {
        size_t h1 = std::hash<vertex>{}(e.first);
        size_t h2 = std::hash<vertex>{}(e.second);
        return h1 ^ (h2 + 0x9e3779b9 + (h1 << 6) + (h1 >> 2));
    }
};

template <typename EdgeBag>
class ParallelAmortizedOrient {
    public:
        #ifdef INSTRUMENT
        std::unordered_map<edge, int, ParallelEdgeHash> flip_counts;
        #endif

        ParallelAmortizedOrient(int n, int c, double epsilon, bool deterministic_grouping = false)
            : n(n),
              c(c),
              epsilon(epsilon),
              tau(static_cast<int>(std::round((24. / 5.) * static_cast<double>(c)))),
              edge_bags(n),
              degrees(n, 0),
              in_vhigh(n, 0),
              deterministic_grouping(deterministic_grouping) {}

        graph orient(const parlay::sequence<edge_batch>& edge_batches) {
            for (const auto& batch : edge_batches) {
                if (batch.first) {
                    insert_batch(batch.second);
                }
                else {
                    delete_batch(batch.second);
                }
            }
            return oriented_graph();
        }

        static graph static_orientation(
                const parlay::sequence<std::pair<vertex, vertex>>& edges,
                int c,
                double epsilon,
                int n,
                bool deterministic_grouping = false) {
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
                auto grouped_edges = group_edges_by_source(active_edges, deterministic_grouping);
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
            auto grouped_oriented_edges = group_edges_by_source(oriented_edges, deterministic_grouping);
            parlay::parallel_for(0, grouped_oriented_edges.size(), [&](size_t i) {
                vertex u = grouped_oriented_edges[i].first;
                oriented_graph[u] = grouped_oriented_edges[i].second;
            });
            return oriented_graph;
        }

    private:
        int n;
        int c;
        double epsilon;
        int tau;
        parlay::sequence<EdgeBag> edge_bags;
        parlay::sequence<size_t> degrees;
        parlay::sequence<unsigned char> in_vhigh;
        bool deterministic_grouping;

        static parlay::sequence<std::pair<vertex, parlay::sequence<vertex>>> group_edges_by_source(
                const parlay::sequence<edge>& edges,
                bool deterministic_grouping) {
            if (deterministic_grouping) {
                return parlay::group_by_key_ordered(edges);
            }
            return parlay::group_by_key(edges);
        }

        void insert_batch(const parlay::sequence<edge>& batch) {
            // Arbitrarily orient the batch as given and add those edges to the graph.
            auto grouped_edges = group_edges_by_source(batch, deterministic_grouping);
            parlay::parallel_for(0, grouped_edges.size(), [&](size_t i) {
                vertex u = grouped_edges[i].first;
                edge_bags[u].batch_insert(grouped_edges[i].second);
            });
            recompute_degrees_and_levels();
            correct_high_vertices();
        }

        void delete_batch(const parlay::sequence<edge>& batch) {
            auto with_reversed_edges = parlay::map(batch, [](const auto& e) {
                auto [u, v] = e;
                return std::make_pair(v, u);
            });
            auto grouped_forward_edges = group_edges_by_source(batch, deterministic_grouping);
            auto grouped_reversed_edges = group_edges_by_source(with_reversed_edges, deterministic_grouping);
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
            recompute_degrees_and_levels();
        }

        void correct_high_vertices() {
            auto vhigh = parlay::filter(parlay::tabulate(n, [](size_t i) {
                return static_cast<vertex>(i);
            }), [&](vertex u) {
                return in_vhigh[u];
            });
            auto high_out_edges = outgoing_edges_for_vertices(vhigh);
            if (high_out_edges.empty()) {
                return;
            }

            parlay::parallel_for(0, vhigh.size(), [&](size_t i) {
                edge_bags[vhigh[i]] = EdgeBag();
            });
            graph statically_oriented = static_orientation(
                high_out_edges, c, epsilon, n, deterministic_grouping);
            #ifdef INSTRUMENT
            record_static_orientation_flips(high_out_edges, statically_oriented);
            #endif
            parlay::parallel_for(0, statically_oriented.size(), [&](size_t u) {
                if (!statically_oriented[u].empty()) {
                    edge_bags[u].batch_insert(statically_oriented[u]);
                }
            });
            recompute_degrees_and_levels();
        }

        parlay::sequence<edge> outgoing_edges_for_vertices(
                const parlay::sequence<vertex>& vertices) const {
            auto vertex_degrees = parlay::tabulate(vertices.size(), [&](size_t i) {
                return edge_bags[vertices[i]].size();
            });
            auto offsets_and_total = parlay::scan(vertex_degrees);
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

        void recompute_degrees_and_levels() {
            parlay::parallel_for(0, edge_bags.size(), [&](size_t i) {
                degrees[i] = edge_bags[i].size();
                in_vhigh[i] = degrees[i] > static_cast<size_t>(tau);
            });
        }

        graph oriented_graph() const {
            graph oriented_graph(n);
            parlay::parallel_for(0, edge_bags.size(), [&](size_t u) {
                oriented_graph[u] = edge_bags[u].to_sequence();
            });
            return oriented_graph;
        }

        #ifdef INSTRUMENT
        void record_static_orientation_flips(
                const parlay::sequence<edge>& original_edges,
                const graph& statically_oriented) {
            std::unordered_set<edge, ParallelEdgeHash> oriented_edges;
            for (size_t u = 0; u < statically_oriented.size(); u++) {
                for (vertex v : statically_oriented[u]) {
                    oriented_edges.insert({static_cast<vertex>(u), v});
                }
            }
            for (const auto& e : original_edges) {
                auto [u, v] = e;
                if (oriented_edges.find({v, u}) != oriented_edges.end()) {
                    increment_flip_count(e);
                }
            }
        }

        void increment_flip_count(const edge& e) {
            auto it = flip_counts.find(e);
            if (it != flip_counts.end()) {
                it->second++;
            }
            else {
                flip_counts[e] = 1;
            }
        }
        #endif
};

graph static_orientation(const parlay::sequence<std::pair<vertex, vertex>>& edges,
                         int c, double epsilon,
                         int n,
                         bool deterministic_grouping = false) {
    return ParallelAmortizedOrient<skew_bag<vertex>>::static_orientation(
        edges, c, epsilon, n, deterministic_grouping);
}

graph parallel_amortized_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int c, double epsilon,
    bool deterministic_grouping = false,
    bool use_hash_table = false) {
    if (use_hash_table) {
        ParallelAmortizedOrient<hash_bag<vertex>> orienter(n, c, epsilon, deterministic_grouping);
        return orienter.orient(edge_batches);
    }
    ParallelAmortizedOrient<skew_bag<vertex>> orienter(n, c, epsilon, deterministic_grouping);
    return orienter.orient(edge_batches);
}
