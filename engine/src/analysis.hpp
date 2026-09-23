#pragma once
#include <nlohmann/json.hpp>

namespace money_graph {
using json = nlohmann::json;
json configuration(const json& overrides = json::object());
json analyze(const json& input, const json& config);
}
