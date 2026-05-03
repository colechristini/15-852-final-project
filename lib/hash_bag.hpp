#pragma once

#include <lib/parlaylib/include/parlay/primitives.h>
#include <lib/parlaylib/include/parlay/sequence.h>
#include <parallel-hashmap/parallel_hashmap/phmap.h>

#include <algorithm>
#include <atomic>
#include <utility>

template <typename T>
class hash_bag {
    using count_map = phmap::parallel_flat_hash_map_m<T, size_t>;

    count_map counts_;
    std::atomic<size_t> size_{0};

    static parlay::sequence<std::pair<T, size_t>> value_counts(
            const parlay::sequence<T>& values) {
        auto keyed_values = parlay::map(values, [](const T& value) {
            return std::make_pair(value, size_t{1});
        });
        return parlay::reduce_by_key(keyed_values);
    }

public:
    hash_bag() = default;

    explicit hash_bag(const parlay::sequence<T>& values) {
        batch_insert(values);
    }

    hash_bag(const hash_bag& other) : size_(other.size()) {
        for (const auto& [value, count] : other.counts_) {
            counts_.emplace(value, count);
        }
    }

    hash_bag& operator=(const hash_bag& other) {
        if (this == &other) {
            return *this;
        }
        count_map next_counts;
        for (const auto& [value, count] : other.counts_) {
            next_counts.emplace(value, count);
        }
        counts_ = std::move(next_counts);
        size_.store(other.size(), std::memory_order_relaxed);
        return *this;
    }

    hash_bag(hash_bag&& other) noexcept
        : counts_(std::move(other.counts_)),
          size_(other.size()) {}

    hash_bag& operator=(hash_bag&& other) noexcept {
        if (this == &other) {
            return *this;
        }
        counts_ = std::move(other.counts_);
        size_.store(other.size(), std::memory_order_relaxed);
        return *this;
    }

    size_t size() const {
        return size_.load(std::memory_order_relaxed);
    }

    bool empty() const {
        return size() == 0;
    }

    parlay::sequence<T> to_sequence() const {
        parlay::sequence<T> out(size());
        if (out.empty()) {
            return out;
        }

        auto submap_sizes = parlay::tabulate(count_map::subcnt(), [&](size_t i) {
            size_t submap_size = 0;
            counts_.with_submap(i, [&](const auto& submap) {
                for (const auto& [value, count] : submap) {
                    (void)value;
                    submap_size += count;
                }
            });
            return submap_size;
        });
        auto offsets_and_total = parlay::scan(submap_sizes);
        const auto& offsets = offsets_and_total.first;

        parlay::parallel_for(0, count_map::subcnt(), [&](size_t i) {
            size_t offset = offsets[i];
            counts_.with_submap(i, [&](const auto& submap) {
                for (const auto& [value, count] : submap) {
                    for (size_t j = 0; j < count; j++) {
                        out[offset++] = value;
                    }
                }
            });
        });
        return out;
    }

    void batch_insert(const parlay::sequence<T>& values) {
        if (values.empty()) {
            return;
        }
        auto grouped_values = value_counts(values);
        parlay::parallel_for(0, grouped_values.size(), [&](size_t i) {
            const T& value = grouped_values[i].first;
            size_t count = grouped_values[i].second;
            counts_.lazy_emplace_l(
                value,
                [&](typename count_map::value_type& p) {
                    p.second += count;
                },
                [&](const typename count_map::constructor& ctor) {
                    ctor(value, count);
                });
        });
        size_.fetch_add(values.size(), std::memory_order_relaxed);
    }

    void batch_delete(const parlay::sequence<T>& values) {
        if (values.empty() || empty()) {
            return;
        }
        auto grouped_values = value_counts(values);
        std::atomic<size_t> deleted_count{0};
        parlay::parallel_for(0, grouped_values.size(), [&](size_t i) {
            const T& value = grouped_values[i].first;
            size_t requested_count = grouped_values[i].second;
            size_t removed_count = 0;
            counts_.erase_if(value, [&](typename count_map::value_type& p) {
                removed_count = std::min(requested_count, p.second);
                p.second -= removed_count;
                return p.second == 0;
            });
            deleted_count.fetch_add(removed_count, std::memory_order_relaxed);
        });
        size_.fetch_sub(deleted_count.load(std::memory_order_relaxed),
                        std::memory_order_relaxed);
    }

    void batchInsert(const parlay::sequence<T>& values) {
        batch_insert(values);
    }

    void batchDelete(const parlay::sequence<T>& values) {
        batch_delete(values);
    }

    parlay::sequence<T> peek(size_t b) const {
        auto values = to_sequence();
        size_t take = std::min(b, values.size());
        return parlay::tabulate(take, [&](size_t i) {
            return values[i];
        });
    }

    parlay::sequence<T> batch_pop(size_t b) {
        auto popped = peek(b);
        batch_delete(popped);
        return popped;
    }

    parlay::sequence<T> batchPop(size_t b) {
        return batch_pop(b);
    }
};
