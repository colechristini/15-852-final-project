#include <../parlaylib/include/parlay/sequence.h>
#include <../parlaylib/include/parlay/primitives.h>
#include <queue>
#include <cassert>


using vertex = int;
using graph = parlay::sequence<parlay::sequence<int>>;
using edge = std::pair<vertex, vertex>;
using edge_batch = parlay::sequence<edge>;


int find_max_degree_vertex_dbg(const parlay::sequence<std::queue<vertex>>& edge_queues) {
    int max_degree_vertex = -1, max_degree = -1;
    for (int j = 0; j < edge_queues.size(); j++) {
        if (!edge_queues[j].empty() && edge_queues[j].size() > max_degree) {
            max_degree_vertex = j;
            max_degree = edge_queues[j].size();
        }
    }
    return max_degree_vertex;
}

vertex find_max_degree_vertex_fast(
    std::priority_queue<std::pair<int, vertex>> degree_queue,
    const parlay::sequence<int>& degrees) {
    while (!degree_queue.empty()) {
        auto [degree, v] = degree_queue.top();
        degree_queue.pop();
        if (degree == degrees[v]) {
            return v;
        }
    }
    return -1;
}

graph sequential_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int k) {
    parlay::sequence<std::queue<vertex>> edge_queues(n);
    parlay::sequence<int> degrees(n, 0);
    std::priority_queue<std::pair<int, vertex>> degree_queue;
    for (const auto& batch : edge_batches) {
        for (const auto& e : batch) {
            int u = e.first;
            int v = e.second;
            edge_queues[u].push(v);
            degrees[u]++;
            degree_queue.push({degrees[u], u});
            for (int i = 0; i < k; i++){
                int max_degree_vertex = find_max_degree_vertex_fast(degree_queue, degrees);
                #ifdef DEBUG
                int max_degree_vertex_dbg = find_max_degree_vertex_dbg(edge_queues);
                assert(max_degree_vertex == max_degree_vertex_dbg);
                int max_degree = edge_queues[max_degree_vertex].size();
                assert(max_degree > 0);
                #endif
                vertex v = edge_queues[max_degree_vertex].front();
                edge_queues[max_degree_vertex].pop();
                edge_queues[v].push(max_degree_vertex);
                degrees[max_degree_vertex]--;
                degrees[v]++;
                degree_queue.push({degrees[max_degree_vertex], max_degree_vertex});
                degree_queue.push({degrees[v], v});
            }
        }     
    }
    graph oriented_graph(n);
    for (vertex u = 0; u < edge_queues.size(); u++) {
        while (!edge_queues[u].empty()) {
            int v = edge_queues[u].front();
            edge_queues[u].pop();
            oriented_graph[u].push_back(v);
        }
    }
    return oriented_graph;
}

