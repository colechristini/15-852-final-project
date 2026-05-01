#include <iostream>
#include <fstream>
#include <lib/parlaylib/include/parlay/sequence.h>
#include<vector>
#include <cmath>
#include "lib/orientation_types.hpp"
#include "sequential_orientation.hpp"
#include "parallel_orientation.hpp"



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


int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <graph_file> <algorithm> <output_file> <parameters>" << std::endl;
        return 1;
    }
    std::string graph_file = argv[1];
    std::string algorithm_name = argv[2];
    std::string output_file = argv[3];
    auto [n, m, edge_batches] = read_edge_batches(graph_file);
    if (algorithm_name == "sequential_amortized" || algorithm_name == "brodal_fagerberg") {
        //compute arboricity here
        graph oriented_graph = sequential_amortized_orient(edge_batches, n, 10);
    }
    else if (algorithm_name == "sequential_worst_case") {
        if (argc >= 5) {
            int k = std::stoi(argv[4]);
            graph oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
        }
        else {
            assert(n > 0);
            int k = static_cast<int>(std::ceil(std::log2(n)));
            graph oriented_graph = sequential_worst_case_orient(edge_batches, n, k);
        }
    }
    else if (algorithm_name == "parallel") {
        
    }
    else {
        std::cerr << "Unknown algorithm: " << algorithm_name << std::endl;
        return 1;
    }
    return 0;
}
