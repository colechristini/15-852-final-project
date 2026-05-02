#pragma once

#include <lib/parlaylib/include/parlay/primitives.h>
#include <lib/parlaylib/include/parlay/sequence.h>

#include <algorithm>
#include <cassert>
#include <map>
#include <memory>
#include <utility>
#include <vector>
#include <cmath>

template <typename T>
class skew_bag {
    struct tree_node {
        T value;
        std::shared_ptr<tree_node> left;
        std::shared_ptr<tree_node> right;
        size_t weight;

        tree_node(T value_,
                  std::shared_ptr<tree_node> left_,
                  std::shared_ptr<tree_node> right_,
                  size_t weight_)
            : value(std::move(value_)),
              left(std::move(left_)),
              right(std::move(right_)),
              weight(weight_) {}
    };

    struct skew_digit {
        size_t weight;
        std::shared_ptr<tree_node> root;
        std::shared_ptr<tree_node> leftmost;
    };

    parlay::sequence<skew_digit> digits_;
    size_t size_ = 0;

    static size_t skew_weight(size_t i) {
        assert(i < 8 * sizeof(size_t));
        return (size_t{1} << i) - 1;
    }

    static parlay::sequence<size_t> skew_init_weights(size_t x) {
        std::vector<size_t> weights;
        if (x == 0) return {};
        // safe since x will never be <= 0
        size_t i = static_cast<size_t>(std::ceil(std::log2(x))) + 1;
        while (x > 0) {
            assert(i > 0);
            size_t w = skew_weight(i);
            if (2 * w == x) {
                weights.push_back(w);
                weights.push_back(w);
                x = 0;
            } else if (w <= x) {
                weights.push_back(w);
                x -= w;
            }
            --i;
        }
        std::reverse(weights.begin(), weights.end());
        return parlay::sequence<size_t>(weights.begin(), weights.end());
    }

    static std::shared_ptr<tree_node> build_complete_tree(
            const parlay::sequence<T>& values,
            size_t begin,
            size_t n) {
        if (n == 0) return nullptr;
        size_t child_n = (n - 1) / 2;

        std::shared_ptr<tree_node> left;
        std::shared_ptr<tree_node> right;
        parlay::par_do(
            [&]() { left = build_complete_tree(values, begin + 1, child_n); },
            [&]() { right = build_complete_tree(values, begin + 1 + child_n, child_n); });

        return std::make_shared<tree_node>(values[begin], std::move(left), std::move(right), n);
    }

    static std::shared_ptr<tree_node> leftmost_of(
            const std::shared_ptr<tree_node>& root) {
        auto cur = root;
        while (cur && cur->left) cur = cur->left;
        return cur;
    }

    static void write_tree(const std::shared_ptr<tree_node>& root,
                           parlay::sequence<T>& out,
                           size_t offset) {
        if (!root) return;
        out[offset] = root->value;
        size_t left_n = root->left ? root->left->weight : 0;
        parlay::par_do(
            [&]() { write_tree(root->left, out, offset + 1); },
            [&]() { write_tree(root->right, out, offset + 1 + left_n); });
    }

    static void write_tree_prefix(const std::shared_ptr<tree_node>& root,
                                  size_t count,
                                  parlay::sequence<T>& out,
                                  size_t offset) {
        if (!root || count == 0) return;
        out[offset] = root->value;
        if (count == 1) return;

        size_t left_n = root->left ? root->left->weight : 0;
        size_t left_take = std::min(left_n, count - 1);
        size_t right_take = count - 1 - left_take;
        parlay::par_do(
            [&]() { write_tree_prefix(root->left, left_take, out, offset + 1); },
            [&]() {
                write_tree_prefix(root->right, right_take, out, offset + 1 + left_take);
            });
    }

    void rebuild_from(parlay::sequence<T> values) {
        size_ = values.size();
        auto weights = skew_init_weights(size_);
        digits_ = parlay::sequence<skew_digit>(weights.size());
        if (weights.empty()) return;
        auto offsets_and_total = parlay::scan(weights);
        const auto& offsets = offsets_and_total.first;
        parlay::parallel_for(0, weights.size(), [&](size_t i) {
            auto root = build_complete_tree(values, offsets[i], weights[i]);
            digits_[i] = skew_digit{weights[i], root, leftmost_of(root)};
        });
    }

public:
    skew_bag() = default;

    explicit skew_bag(const parlay::sequence<T>& values) {
        rebuild_from(values);
    }

    size_t size() const {
        return size_;
    }

    bool empty() const {
        return size_ == 0;
    }

    parlay::sequence<T> to_sequence() const {
        parlay::sequence<T> out(size_);
        if (size_ == 0) return out;
        auto weights = parlay::tabulate(digits_.size(), [&](size_t i) {
            return digits_[i].weight;
        });
        auto offsets_and_total = parlay::scan(weights);
        const auto& offsets = offsets_and_total.first;
        parlay::parallel_for(0, digits_.size(), [&](size_t i) {
            write_tree(digits_[i].root, out, offsets[i]);
        });
        return out;
    }

    parlay::sequence<T> peek(size_t b) const {
        size_t take = std::min(b, size_);
        parlay::sequence<T> out(take);
        if (take == 0) return out;
        size_t offset = 0;
        for (const auto& digit : digits_) {
            if (offset + digit.weight <= take) {
                write_tree(digit.root, out, offset);
                offset += digit.weight;
            } else {
                write_tree_prefix(digit.root, take - offset, out, offset);
                break;
            }
        }
        return out;
    }

    void batchInsert(const parlay::sequence<T>& values) {
        if (values.empty()) return;
        auto current = to_sequence();
        parlay::sequence<T> next(size_ + values.size());
        parlay::parallel_for(0, current.size(), [&](size_t i) {
            next[i] = current[i];
        });
        parlay::parallel_for(0, values.size(), [&](size_t i) {
            next[current.size() + i] = values[i];
        });
        rebuild_from(std::move(next));
    }

    void batch_insert(const parlay::sequence<T>& values) {
        batchInsert(values);
    }

    void batchDelete(const parlay::sequence<T>& values) {
        if (values.empty() || empty()) return;
        std::map<T, size_t> remaining_deletes;
        for (const auto& value : values) ++remaining_deletes[value];
        std::vector<T> kept;
        kept.reserve(size_);
        auto current = to_sequence();
        for (const auto& value : current) {
            auto it = remaining_deletes.find(value);
            if (it == remaining_deletes.end() || it->second == 0) {
                kept.push_back(value);
            } else {
                --it->second;
            }
        }
        rebuild_from(parlay::sequence<T>(kept.begin(), kept.end()));
    }

    void batch_delete(const parlay::sequence<T>& values) {
        batchDelete(values);
    }

    parlay::sequence<T> batchPop(size_t b) {
        size_t take = std::min(b, size_);
        auto popped = peek(take);
        if (take == 0) return popped;
        auto current = to_sequence();
        parlay::sequence<T> kept(size_ - take);
        parlay::parallel_for(0, kept.size(), [&](size_t i) {
            kept[i] = current[take + i];
        });
        rebuild_from(std::move(kept));
        return popped;
    }

    parlay::sequence<T> batch_pop(size_t b) {
        return batchPop(b);
    }
};

