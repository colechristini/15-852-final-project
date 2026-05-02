#include <iostream>
#include <fstream>
#include <lib/parlaylib/include/parlay/sequence.h>
#include<vector>
#include <cmath>
#include "lib/orientation_types.hpp"
#include "sequential_orientation.hpp"
#include "parallel_orientation.hpp"
#include <lib/compute_orientation_quality.hpp>
#include "lib/approximate_arboricity.hpp"
#include <chrono>

std::tuple<int, int, parlay::sequence<edge_batch>> read_edge_batches(const std::string& filename) {
    int n, m, num_batches;
    std::ifstream infile(filename);
    infile >> n >> m >> num_batches;
    std::vector<std::pair<bool, int>> batch_sizes(num_batches);
    for (int i = 0; i < num_batches; i++) {
        infile >> batch_sizes[i].first >> batch_sizes[i].second;
    }
    parlay::sequence<edge_batch> edge_batches(num_batches);
    for (int i = 0; i < num_batches; i++) {
        edge_batch batch(batch_sizes[i]);
        batch.first = batch_sizes[i].first;
        batch.second.resize(batch_sizes[i].second);
        for (int j = 0; j < batch_sizes[i].second; j++) {
            int u, v;
            infile >> u >> v;
            batch.second[j] = {u, v};
        }
        edge_batches[i] = std::move(batch);
    }
    return {n, m, edge_batches};
}

void write_oriented_graph(const graph& oriented_graph, const std::string& filename) {
    std::ofstream outfile(filename);
    int n = oriented_graph.size();
    int m = 0;
    for (const auto& neighbors : oriented_graph) {
        m += neighbors.size();
    }
    outfile << n << " " << m << "\n";
    for (vertex u = 0; u < oriented_graph.size(); u++) {
        for (vertex v : oriented_graph[u]) {
            outfile << u << " " << v << "\n";
        }
    }
}

int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <graph_file> <algorithm> <output_file> <parameters>" << std::endl;
        return 1;
    }
    std::string graph_file = argv[1];
    std::string algorithm_name = argv[2];
    std::string output_file = argv[3];
    auto [n, m, edge_batches] = read_edge_batches(graph_file);
    graph oriented_graph;
    long long nanos;
    if (algorithm_name == "sequential_amortized" || algorithm_name == "brodal_fagerberg") {
        int arboricity = compute_approximate_arboricity(edge_batches, n);
        auto start = std::chrono::high_resolution_clock::now();
        oriented_graph = sequential_amortized_orient(edge_batches, n, 10);
        auto end = std::chrono::high_resolution_clock::now();
        nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    }
    else if (algorithm_name == "sequential_worst_case") {
        if (argc >= 6 && std::string(argv[4]) == "-k") {
            int k = std::stoi(argv[5]);
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        }
        else {
            assert(n > 0);
            int k = static_cast<int>(std::ceil(std::log2(n)));
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        }
    }
    else if (algorithm_name == "parallel") {
        if (argc >= 8  && std::string(argv[4]) == "-c" && std::string(argv[6]) == "-eps") {
            int c = std::stoi(argv[5]);
            double eps = std::stod(argv[7]);
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = parallel_amortized_orient(edge_batches, n, c, eps);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        }
        else return 1;
    }
    else {
        std::cerr << "Unknown algorithm: " << algorithm_name << std::endl;
        return 1;
    }
    size_t max_out_degree = compute_max_out_degree(oriented_graph);
    double average_out_degree = compute_average_out_degree(oriented_graph);
    std::cout << "Time taken (ns): " << nanos << std::endl;
    std::cout << "Max out-degree: " << max_out_degree << std::endl;
    std::cout << "Average out-degree: " << average_out_degree << std::endl;
    write_oriented_graph(oriented_graph, output_file);
    return 0;
}
