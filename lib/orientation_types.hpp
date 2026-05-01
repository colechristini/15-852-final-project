#pragma once

#include <parlaylib/include/parlay/sequence.h>

using vertex = int;
using graph = parlay::sequence<parlay::sequence<int>>;
using edge = std::pair<vertex, vertex>;
using edge_batch = std::pair<bool, parlay::sequence<edge>>;