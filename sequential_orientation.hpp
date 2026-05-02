#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <algorithm>
#include <deque>
#include <queue>
#include <cassert>
#include <vector>




class SequentialWorstCaseOrient{
    public: 
        #ifdef INSTRUMENT
        std::unordered_map<edge, int> flip_counts;
        #endif
        SequentialWorstCaseOrient(int n, int k)
            : edge_queues(n), degrees(n, 0), k(k) {}

        graph orient(const parlay::sequence<edge_batch>& edge_batches) {
            for (const auto &batch : edge_batches) {
                bool is_insert = batch.first;
                for (const auto& e : batch.second) {
                    if (is_insert) {
                        insert_edge(e);
                    }
                    else {
                        delete_edge(e);
                    }
                    k_flips();
                }
            }
            return oriented_graph();
        }

    private:
        std::priority_queue<std::pair<int, vertex>> degree_queue;
        parlay::sequence<std::deque<vertex>> edge_queues;
        parlay::sequence<int> degrees;
        int k;
        

        #ifdef DEBUG
            vertex find_max_degree_vertex_dbg() const {
                int max_degree_vertex = -1;
                size_t max_degree = 0;
                for (size_t j = 0; j < edge_queues.size(); j++) {
                    if (!edge_queues[j].empty() && edge_queues[j].size() > max_degree) {
                        max_degree_vertex = static_cast<vertex>(j);
                        max_degree = edge_queues[j].size();
                    }
                }
                return max_degree_vertex;
            }
        #endif

        vertex find_max_degree_vertex() {
            while (!degree_queue.empty()) {
                auto [degree, v] = degree_queue.top();
                if (degree == degrees[v]) {
                    return v;
                }
                degree_queue.pop();
            }
            return -1;
        }

        void k_flips() {
            for (int i = 0; i < k; i++){
                int max_degree_vertex = find_max_degree_vertex();
                #ifdef DEBUG
                        int max_degree_vertex_dbg = find_max_degree_vertex_dbg();
                        assert(max_degree_vertex == max_degree_vertex_dbg);
                        int max_degree = edge_queues[max_degree_vertex].size();
                        assert(max_degree > 0);
                #endif
                vertex v = edge_queues[max_degree_vertex].front();
                edge_queues[max_degree_vertex].pop_front();
                #ifdef INSTRUMENT
                edge e = std::make_pair(max_degree_vertex, v);
                auto it = flip_counts.find(e);
                if (it != flip_counts.end()) {
                    flip_counts[e]++;
                }
                else flip_counts[e] = 1;
                #endif
                edge_queues[v].push_back(max_degree_vertex);
                degrees[max_degree_vertex]--;
                degrees[v]++;
                degree_queue.push({degrees[max_degree_vertex], max_degree_vertex});
                degree_queue.push({degrees[v], v});
            }
        }

        void insert_edge(const edge& e) {
            auto [u, v] = e;
            edge_queues[u].push_back(v);
            degrees[u]++;
            degree_queue.push({degrees[u], u});
        }

        void delete_edge(const edge& e) {
            auto [u, v] = e;
            auto it_u = std::find(edge_queues[u].begin(), edge_queues[u].end(), v);
            if (it_u != edge_queues[u].end()) {
                edge_queues[u].erase(it_u);
                degrees[u]--;
                degree_queue.push({degrees[u], u});
                return;
            }

            auto it_v = std::find(edge_queues[v].begin(), edge_queues[v].end(), u);
            assert(it_v != edge_queues[v].end());
            edge_queues[v].erase(it_v);
            degrees[v]--;
            degree_queue.push({degrees[v], v});
        }

        graph oriented_graph() {
            graph oriented_graph(edge_queues.size());
            for (size_t u = 0; u < edge_queues.size(); u++) {
                while (!edge_queues[u].empty()) {
                    int v = edge_queues[u].front();
                    edge_queues[u].pop_front();
                    oriented_graph[u].push_back(v);
                }
            }
            return oriented_graph;
        }
};

graph sequential_worst_case_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int k) {
    SequentialWorstCaseOrient orienter(n, k);
    return orienter.orient(edge_batches);
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
