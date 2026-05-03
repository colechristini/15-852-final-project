#include <lib/orientation_types.hpp>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <algorithm>
#include <deque>
#include <queue>
#include <cassert>
#include <unordered_map>
#include <vector>


struct EdgeHash {
    size_t operator()(const edge& e) const {
        size_t h1 = std::hash<vertex>{}(e.first);
        size_t h2 = std::hash<vertex>{}(e.second);
        return h1 ^ (h2 + 0x9e3779b9 + (h1 << 6) + (h1 >> 2));
    }
};



class SequentialWorstCaseOrient{
    public: 
        #ifdef INSTRUMENT
        std::unordered_map<edge, int, EdgeHash> flip_counts;
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
                increment_flip_count(e);
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

        #ifdef INSTRUMENT
        edge canonical_edge(const edge& e) const {
            auto [u, v] = e;
            if (u < v) {
                return e;
            }
            return {v, u};
        }

        void increment_flip_count(const edge& e) {
            edge key = canonical_edge(e);
            auto it = flip_counts.find(key);
            if (it != flip_counts.end()) {
                it->second++;
            }
            else {
                flip_counts[key] = 1;
            }
        }
        #endif
};

graph sequential_worst_case_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int k) {
    SequentialWorstCaseOrient orienter(n, k);
    return orienter.orient(edge_batches);
}

class SequentialAmortizedOrient {
    public:
        #ifdef INSTRUMENT
        std::unordered_map<edge, int, EdgeHash> flip_counts;
        #endif

        SequentialAmortizedOrient(int n, int c)
            : edge_lists(n), degrees(n, 0), c(c) {}

        graph orient(const parlay::sequence<edge_batch>& edge_batches) {
            for (const auto& batch : edge_batches) {
                bool is_insert = batch.first;
                for (const auto& e : batch.second) {
                    if (is_insert) {
                        insert_edge(e);
                    }
                    else {
                        delete_edge(e);
                    }
                }
                correct_edges();
            }
            return oriented_graph();
        }

    private:
        std::vector<std::vector<vertex>> edge_lists;
        std::priority_queue<std::pair<int, vertex>> degree_queue;
        parlay::sequence<int> degrees;
        int c;

        void insert_edge(const edge& e) {
            auto [u, v] = e;
            degrees[u]++;
            degree_queue.push({degrees[u], u});
            edge_lists[u].push_back(v);
        }

        void delete_edge(const edge& e) {
            auto [u, v] = e;
            auto it_u = std::find(edge_lists[u].begin(), edge_lists[u].end(), v);
            if (it_u != edge_lists[u].end()) {
                edge_lists[u].erase(it_u);
                degrees[u]--;
                degree_queue.push({degrees[u], u});
                return;
            }

            auto it_v = std::find(edge_lists[v].begin(), edge_lists[v].end(), u);
            assert(it_v != edge_lists[v].end());
            edge_lists[v].erase(it_v);
            degrees[v]--;
            degree_queue.push({degrees[v], v});
        }

        void correct_edges() {
            while (!degree_queue.empty()) {
                auto [max_degree, u] = degree_queue.top();
                if (degrees[u] != max_degree) {
                    degree_queue.pop();
                    continue;
                }
                if (max_degree <= 4 * c) {
                    return;
                }

                degree_queue.pop();
                for (auto v : edge_lists[u]) {
                    edge_lists[v].push_back(u);
                    degrees[v]++;
                    #ifdef INSTRUMENT
                    increment_flip_count({u, v});
                    #endif
                    // this is definitely suboptimal.. maybe if we use sequences for the edge lists
                    // we can use semisort to group them together and only push the final numbers in?
                    degree_queue.push({degrees[v], v});
                }
                edge_lists[u].clear();
                degrees[u] = 0;
                degree_queue.push({degrees[u], u});
            }
        }

        graph oriented_graph() const {
            graph oriented_graph(edge_lists.size());
            for (size_t u = 0; u < edge_lists.size(); u++) {
                oriented_graph[u] = parlay::sequence<vertex>::from_function(
                    edge_lists[u].size(),
                    [&](size_t i) { return edge_lists[u][i]; });
            }
            return oriented_graph;
        }

        #ifdef INSTRUMENT
        edge canonical_edge(const edge& e) const {
            auto [u, v] = e;
            if (u < v) {
                return e;
            }
            return {v, u};
        }

        void increment_flip_count(const edge& e) {
            edge key = canonical_edge(e);
            auto it = flip_counts.find(key);
            if (it != flip_counts.end()) {
                it->second++;
            }
            else {
                flip_counts[key] = 1;
            }
        }
        #endif
};

graph sequential_amortized_orient(
    const parlay::sequence<edge_batch>& edge_batches,
    int n, int c) {
    SequentialAmortizedOrient orienter(n, c);
    return orienter.orient(edge_batches);
}
