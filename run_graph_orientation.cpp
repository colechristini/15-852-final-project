#include <iostream>
#include <fstream>
#include <parlaylib/include/parlay/sequence.h>
#include<vector>
#include "implementations/sequential.h"
#include "implementations/parallel.h"


using graph = parlay::sequence<parlay::sequence<int>>;
using edge = std::pair<int, int>;
using edge_batch = parlay::sequence<edge>;


parlay::sequence<edge_batch> read_edge_batches(const std::string& filename) {
    int n, m, num_batches;
    std::ifstream infile(filename);
    infile >> n >> m >> num_batches;
    std::vector<int> batch_sizes(num_batches);
    for (int i = 0; i < num_batches; i++) {
        infile >> batch_sizes[i];
    }
    parlay::sequence<edge_batch> edge_batches(num_batches);
    for (int i = 0; i < num_batches; i++) {
        edge_batch batch(batch_sizes[i]);
        for (int j = 0; j < batch_sizes[i]; j++) {
            int u, v;
            infile >> u >> v;
            batch[j] = {u, v};
        }
        edge_batches[i] = std::move(batch);
    }
    return edge_batches;
}


int main(int argc, char* argv[]) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <graph_file> <algorithm> <output_file>" << std::endl;
        return 1;
    }
    std::string graph_file = argv[1];
    std::string algorithm_name = argv[2];
    std::string output_file = argv[3];
    parlay::sequence<edge_batch> edge_batches = read_edge_batches(graph_file);
    if (algorithm_name == "sequential") {
        graph oriented_graph = sequential_orient(edge_batches, 0, 0);
    }
    else if (algorithm_name == "parallel") {
        
    }
    else {
        std::cerr << "Unknown algorithm: " << algorithm_name << std::endl;
        return 1;
    }
    return 0;
}
