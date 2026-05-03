#include <iostream>
#include <fstream>
#include <lib/parlaylib/include/parlay/sequence.h>
#include<vector>
#include <cmath>
#include "lib/orientation_types.hpp"
#include "sequential_orientation.hpp"
#include "parallel_orientation.hpp"
#include <lib/compute_orientation_quality.hpp>
#include <chrono>
#include <algorithm>

#ifdef INSTRUMENT
struct FlipStats {
    double mean = 0.0;
    int maximum = 0;
    long long total = 0;
    size_t flipped_edges = 0;
};

template <typename FlipCounts>
FlipStats compute_flip_stats(const FlipCounts& flip_counts) {
    if (flip_counts.empty()) {
        return {};
    }

    FlipStats stats;
    for (const auto& entry : flip_counts) {
        stats.total += entry.second;
        stats.maximum = std::max(stats.maximum, entry.second);
    }
    stats.flipped_edges = flip_counts.size();
    stats.mean = static_cast<double>(stats.total) / static_cast<double>(stats.flipped_edges);
    return stats;
}
#endif

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
        std::cerr << "Usage: " << argv[0]
                  << " <graph_file> <algorithm> <output_file> <parameters>\n"
                  << "Sequential amortized parameters: [-c <c>]\n"
                  << "Parallel parameters: -c <c> -eps <epsilon> [--deterministic-sort] [--hash-table] "
                  << "[--flip-low-high-out-edges] [--flip-low-high-out-edges-threshold <k>] "
                  << "[--flip-all-high-vertices]"
                  << std::endl;
        return 1;
    }
    std::string graph_file = argv[1];
    std::string algorithm_name = argv[2];
    std::string output_file = argv[3];
    auto [n, m, edge_batches] = read_edge_batches(graph_file);
    graph oriented_graph;
    long long nanos;
    #ifdef INSTRUMENT
    FlipStats flip_stats;
    #endif
    if (algorithm_name == "sequential_amortized" || algorithm_name == "brodal_fagerberg") {
        int c = 10;
        if (argc >= 6 && std::string(argv[4]) == "-c") {
            c = std::stoi(argv[5]);
        }
        else if (argc > 4) {
            std::cerr << "Unknown sequential amortized option: " << argv[4] << std::endl;
            return 1;
        }
        #ifdef INSTRUMENT
        SequentialAmortizedOrient orienter(n, c);
        auto start = std::chrono::high_resolution_clock::now();
        oriented_graph = orienter.orient(edge_batches);
        auto end = std::chrono::high_resolution_clock::now();
        nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        flip_stats = compute_flip_stats(orienter.flip_counts);
        #else
        auto start = std::chrono::high_resolution_clock::now();
        oriented_graph = sequential_amortized_orient(edge_batches, n, c);
        auto end = std::chrono::high_resolution_clock::now();
        nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        #endif
    }
    else if (algorithm_name == "sequential_worst_case") {
        if (argc >= 6 && std::string(argv[4]) == "-k") {
            int k = std::stoi(argv[5]);
            #ifdef INSTRUMENT
            SequentialWorstCaseOrient orienter(n, k);
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = orienter.orient(edge_batches);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            flip_stats = compute_flip_stats(orienter.flip_counts);
            #else
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            #endif
        }
        else {
            assert(n > 0);
            int k = static_cast<int>(std::ceil(std::log2(n)));
            #ifdef INSTRUMENT
            SequentialWorstCaseOrient orienter(n, k);
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = orienter.orient(edge_batches);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            flip_stats = compute_flip_stats(orienter.flip_counts);
            #else
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            #endif
        }
    }
    else if (algorithm_name == "parallel") {
        if (argc >= 8  && std::string(argv[4]) == "-c" && std::string(argv[6]) == "-eps") {
            int c = std::stoi(argv[5]);
            double eps = std::stod(argv[7]);
            bool deterministic_sort = false;
            bool use_hash_table = false;
            bool flip_low_high_out_edges = false;
            size_t low_high_vertex_threshold = static_cast<size_t>(c);
            for (int i = 8; i < argc; i++) {
                std::string option = argv[i];
                if (option == "--deterministic-sort" || option == "--ordered-group-by") {
                    deterministic_sort = true;
                }
                else if (option == "--hash-table") {
                    use_hash_table = true;
                }
                else if (option == "--flip-low-high-out-edges") {
                    flip_low_high_out_edges = true;
                }
                else if (option == "--flip-all-high-vertices") {
                    flip_low_high_out_edges = true;
                    low_high_vertex_threshold = static_cast<size_t>(n);
                }
                else if (option == "--flip-low-high-out-edges-threshold") {
                    if (i + 1 >= argc) {
                        std::cerr << "Missing value for parallel option: " << option << std::endl;
                        return 1;
                    }
                    flip_low_high_out_edges = true;
                    low_high_vertex_threshold = static_cast<size_t>(std::stoull(argv[++i]));
                }
                else {
                    std::cerr << "Unknown parallel option: " << option << std::endl;
                    return 1;
                }
            }
            std::cout << "RUnning parallel algo" << std::endl;
            #ifdef INSTRUMENT
            auto start = std::chrono::high_resolution_clock::now();
            if (use_hash_table) {
                ParallelAmortizedOrient<hash_bag<vertex>> orienter(
                    n,
                    c,
                    eps,
                    deterministic_sort,
                    flip_low_high_out_edges,
                    low_high_vertex_threshold);
                oriented_graph = orienter.orient(edge_batches);
                flip_stats = compute_flip_stats(orienter.flip_counts);
            }
            else {
                ParallelAmortizedOrient<skew_bag<vertex>> orienter(
                    n,
                    c,
                    eps,
                    deterministic_sort,
                    flip_low_high_out_edges,
                    low_high_vertex_threshold);
                oriented_graph = orienter.orient(edge_batches);
                flip_stats = compute_flip_stats(orienter.flip_counts);
            }
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            #else
            auto start = std::chrono::high_resolution_clock::now();
            oriented_graph = parallel_amortized_orient(
                edge_batches,
                n,
                c,
                eps,
                deterministic_sort,
                use_hash_table,
                flip_low_high_out_edges,
                low_high_vertex_threshold);
            auto end = std::chrono::high_resolution_clock::now();
            nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
            #endif
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
    #ifdef INSTRUMENT
    std::cout << "Mean flips: " << flip_stats.mean << std::endl;
    std::cout << "Max flips: " << flip_stats.maximum << std::endl;
    std::cout << "Total flips: " << flip_stats.total << std::endl;
    std::cout << "Flipped edges: " << flip_stats.flipped_edges << std::endl;
    #endif
    write_oriented_graph(oriented_graph, output_file);
    return 0;
}
