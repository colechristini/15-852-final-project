#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <deque>
#include <queue>
#include <cassert>




#ifdef DEBUG
int find_max_degree_vertex_dbg(const parlay::sequence<std::deque<vertex>>& edge_queues) {
    int max_degree_vertex = -1, max_degree = -1;
    for (int j = 0; j < edge_queues.size(); j++) {
        if (!edge_queues[j].empty() && edge_queues[j].size() > max_degree) {
            max_degree_vertex = j;
            max_degree = edge_queues[j].size();
        }
    }
    return max_degree_vertex;
}
#endif

vertex find_max_degree_vertex(
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

void k_flips(std::priority_queue<std::pair<int, vertex>>& degree_queue,
             parlay::sequence<std::deque<vertex>>& edge_queues,
             parlay::sequence<int>& degrees, int k) {
    for (int i = 0; i < k; i++){
        int max_degree_vertex = find_max_degree_vertex(degree_queue, degrees);
        #ifdef DEBUG
        int max_degree_vertex_dbg = find_max_degree_vertex_dbg(edge_queues);
        assert(max_degree_vertex == max_degree_vertex_dbg);
        int max_degree = edge_queues[max_degree_vertex].size();
        assert(max_degree > 0);
        #endif
        vertex v = edge_queues[max_degree_vertex].front();
        edge_queues[max_degree_vertex].pop_front();
        edge_queues[v].push_back(max_degree_vertex);
        degrees[max_degree_vertex]--;
        degrees[v]++;
        degree_queue.push({degrees[max_degree_vertex], max_degree_vertex});
        degree_queue.push({degrees[v], v});
    }
}

graph sequential_worst_case_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int k) {
    parlay::sequence<std::deque<vertex>> edge_queues(n);
    parlay::sequence<int> degrees(n, 0);
    std::priority_queue<std::pair<int, vertex>> degree_queue;
    for (auto &batch : edge_batches) {
        bool is_insert = batch.first;
        for (const auto& e : batch.second) {
            auto [u, v] = e;
            if (is_insert) { //technically we could lift this branch outside of the for to avoid evaluating for every edge
                edge_queues[u].push_back(v);
                degrees[u]++;
                degree_queue.push({degrees[u], u});
            }
            else {
                auto it_u = std::find(edge_queues[u].begin(), edge_queues[u].end(), v);
                if (it_u != edge_queues[u].end()) {
                    edge_queues[u].erase(it_u);
                    degrees[u]--;
                    degree_queue.push({degrees[u], u});
                }
                else {
                    auto it_v = std::find(edge_queues[v].begin(), edge_queues[v].end(), u);
                    assert(it_v != edge_queues[v].end());
                    edge_queues[v].erase(it_v);
                    degrees[v]--;
                    degree_queue.push({degrees[v], v});
                }
            }
            k_flips(degree_queue, edge_queues, degrees, k);
        }     
    }
    graph oriented_graph(n);
    for (vertex u = 0; u < edge_queues.size(); u++) {
        while (!edge_queues[u].empty()) {
            int v = edge_queues[u].front();
            edge_queues[u].pop_front();
            oriented_graph[u].push_back(v);
        }
    }
    return oriented_graph;
}

void correct_edges(std::vector<std::vector<vertex>>& edge_lists, std::priority_queue<std::pair<int, vertex>>& degree_queue, parlay::sequence<int>& degrees, int c) {
    auto [max_degree, u] = degree_queue.top();
    while (max_degree > c) {
        degree_queue.pop();
        if (degrees[u] != max_degree) continue;
        for (auto v : edge_lists[u]) {
            edge_lists[v].push_back(u);
            degrees[v]++;
            // this is definitely suboptimal.. maybe if we use sequences for the edge lists
            // we can use semisort to group them together and only push the final numbers in?
            degree_queue.push({degrees[v], v}); 
        }
        edge_lists[u].clear();
        degrees[u] = 0;
        degree_queue.push({degrees[u], u});
        auto [new_max_degree, new_u] = degree_queue.top();
        max_degree = new_max_degree, u = new_u;
    }
}

graph sequential_amortized_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int c) {
    parlay::sequence<int> degrees(n, 0);
    std::priority_queue<std::pair<int, vertex>> degree_queue;
    std::vector<std::vector<vertex>> edge_lists(n); // no reason we couldnt make these sequences tbh
    for (auto &batch : edge_batches) {
        bool is_insert = batch.first;
        for (const auto& e : batch.second) {
            auto [u, v] = e;
            if (is_insert) {
                degrees[u]++;
                degree_queue.push({degrees[u], u});
                edge_lists[u].push_back(v);
            }
            else {
                auto it_u = std::find(edge_lists[u].begin(), edge_lists[u].end(), v);
                if (it_u != edge_lists[u].end()) {
                    edge_lists[u].erase(it_u);
                    degrees[u]--;
                    degree_queue.push({degrees[u], u});
                }
                else {
                    auto it_v = std::find(edge_lists[v].begin(), edge_lists[v].end(), u);
                    assert(it_v != edge_lists[v].end());
                    edge_lists[v].erase(it_v);
                    degrees[v]--;
                    degree_queue.push({degrees[v], v});
                }
            }
        }
        correct_edges(edge_lists, degree_queue, degrees, c);     
    }
    graph oriented_graph(n);
    return oriented_graph;
}

