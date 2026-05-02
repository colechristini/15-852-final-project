#include "orientation_types.hpp"

size_t compute_max_out_degree(const graph& oriented_graph) {
    size_t max_out_degree = 0;
    for (const auto& neighbors : oriented_graph) {
        size_t out_degree = neighbors.size();
        if (out_degree > max_out_degree) {
            max_out_degree = out_degree;
        }
    }
    return max_out_degree;
}

double compute_max_out_degree_multiple(const graph& oriented_graph, int c) {
    return static_cast<double>(compute_max_out_degree(oriented_graph)) / c;
}

double compute_average_out_degree(const graph& oriented_graph) {
    size_t total_out_degree = 0;
    for (const auto& neighbors : oriented_graph) {
        total_out_degree += neighbors.size();
    }
    return static_cast<double>(total_out_degree) / oriented_graph.size();
}

