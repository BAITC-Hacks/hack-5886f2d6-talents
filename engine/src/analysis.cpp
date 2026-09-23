#include "analysis.hpp"
#include "default_config.hpp"
#include <algorithm>
#include <charconv>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <vector>

namespace money_graph {
namespace {
[[noreturn]] void fail(const std::string& message) { throw std::runtime_error(message); }

double number(const json& value, const std::string& field) {
    if (!value.is_number()) fail(field + " must be a finite nonnegative number");
    const double n = value.get<double>();
    if (!std::isfinite(n) || n < 0) fail(field + " must be a finite nonnegative number");
    return n;
}

std::int64_t integer(const json& value, const std::string& field) {
    if (!value.is_number_integer() ||
        (value.is_number_unsigned() && value.get<std::uint64_t>() >
            static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max())))
        fail(field + " must be a nonnegative int64");
    const auto n = value.get<std::int64_t>();
    if (n < 0) fail(field + " must be a nonnegative int64");
    return n;
}

bool boolean(const json& value, const std::string& field) {
    if (!value.is_boolean()) fail(field + " must be boolean");
    return value.get<bool>();
}

std::string identifier(const json& value, const std::string& field) {
    if (!value.is_string()) fail(field + " must be an int64 encoded as a string");
    const auto s = value.get<std::string>();
    std::int64_t id = 0;
    const auto parsed = std::from_chars(s.data(), s.data() + s.size(), id);
    if (parsed.ec != std::errc() || parsed.ptr != s.data() + s.size() || s != std::to_string(id))
        fail(field + " must be a canonical int64 string");
    return s;
}

bool close(double a, double b) {
    return std::abs(a - b) <= 0.01 + 1e-9 * std::max(std::abs(a), std::abs(b));
}

double bounded(double x) { return std::clamp(x, 0.0, 1.0); }
double saturation(double value, double limit) { return bounded(value / limit); }

std::string fmt(double value) {
    std::ostringstream out;
    out.imbue(std::locale::classic());
    if (value >= 1e12) out << std::scientific << std::setprecision(2) << value;
    else out << std::fixed << std::setprecision(value < 10 ? 2 : 0) << value;
    return out.str();
}

// Count Unicode code points rather than UTF-8 bytes. All strings are built from
// validated data and UTF-8 source literals, so we only need character boundaries.
std::string short_text(const std::string& text) {
    std::size_t count = 0;
    for (std::size_t i = 0; i < text.size(); ++i) {
        if ((static_cast<unsigned char>(text[i]) & 0xc0) != 0x80 && ++count > 200)
            return text.substr(0, i);
    }
    return text;
}

struct Node {
    std::string gid;
    std::int64_t numeric_gid = 0, depth = 0, cluster = 0;
    std::int64_t in_deg = 0, out_deg = 0, in_tx = 0, out_tx = 0;
    bool seed = false;
    double in_kzt = 0, out_kzt = 0, pagerank = 0, self_kzt = 0;
    std::vector<std::size_t> incoming, outgoing;
    std::size_t seed_reach = 0, direct_seeds = 0, peers = 0, external_clusters = 0;
    std::size_t cross_edges = 0, nonself_in = 0, nonself_out = 0;
    std::int64_t min_hops = -1;
};
struct Edge { std::size_t src, dst; double sum; std::int64_t count; };

std::vector<double> percentiles(const std::vector<double>& values) {
    std::vector<double> positive;
    for (const double v : values) if (v > 0) positive.push_back(v);
    std::sort(positive.begin(), positive.end());
    std::vector<double> result(values.size(), 0);
    if (positive.empty()) return result;
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (values[i] > 0)
            result[i] = static_cast<double>(std::upper_bound(positive.begin(), positive.end(), values[i])
                - positive.begin()) / static_cast<double>(positive.size());
    }
    return result;
}

void add_count(std::int64_t& target, std::int64_t delta) {
    if (delta > std::numeric_limits<std::int64_t>::max() - target) fail("Transaction count overflow");
    target += delta;
}
} // namespace

json configuration(const json& overrides) {
    json config = json::parse(DEFAULT_CONFIG_JSON);
    if (!overrides.is_object()) fail("Config must be an object");
    for (const auto& item : overrides.items()) {
        if (!config.contains(item.key())) fail("Unknown config key: " + item.key());
        if (item.key() == "priority_weights") {
            if (!item.value().is_object()) fail("priority_weights must be an object");
            for (const auto& weight : item.value().items()) {
                if (!config[item.key()].contains(weight.key())) fail("Unknown priority weight: " + weight.key());
                config[item.key()][weight.key()] = weight.value();
            }
        } else config[item.key()] = item.value();
    }
    for (const auto& item : config.items()) {
        if (item.key() == "priority_weights") continue;
        const auto value = number(item.value(), item.key());
        if (item.key().find("percentile") != std::string::npos ||
            item.key().find("multiplier") != std::string::npos) {
            if (value > 1) fail(item.key() + " must be in [0,1]");
        } else if (value <= 0) fail(item.key() + " must be positive");
        if (item.key() == "max_depth" || item.key().find("_min_senders") != std::string::npos ||
            item.key().find("_min_receivers") != std::string::npos ||
            item.key() == "coordinator_min_seeds" || item.key() == "coordinator_min_external_clusters")
            integer(item.value(), item.key());
    }
    if (config["transit_ratio_min"].get<double>() >= 1 || config["transit_ratio_max"].get<double>() <= 1)
        fail("Transit interval must contain 1 strictly");
    double total = 0;
    for (const auto& item : config["priority_weights"].items()) total += number(item.value(), item.key());
    if (!std::isfinite(total) || std::abs(total - 1) > 1e-9) fail("Priority weights must sum to 1");
    return config;
}

json analyze(const json& input, const json& config) {
    if (!input.is_object() || input.at("schema_version") != "1.0") fail("schema_version must be '1.0'");
    if (!input.at("nodes").is_array() || !input.at("edges").is_array()) fail("nodes and edges must be arrays");
    const auto max_depth = config.at("max_depth").get<std::int64_t>();
    const auto cfg = [&](const char* key) { return config.at(key).get<double>(); };
    std::vector<Node> nodes;
    std::unordered_map<std::string, std::size_t> index;
    std::unordered_map<std::string, const json*> source_nodes;
    for (const auto& row : input.at("nodes")) {
        Node n;
        n.gid = identifier(row.at("gid"), "gid");
        n.numeric_gid = std::stoll(n.gid);
        n.depth = integer(row.at("depth"), n.gid + ".depth");
        if (n.depth > max_depth) fail(n.gid + ": depth exceeds max_depth");
        n.cluster = integer(row.at("cluster_id"), n.gid + ".cluster_id");
        n.seed = boolean(row.at("is_seed"), n.gid + ".is_seed");
        n.in_deg = integer(row.at("in_deg"), n.gid + ".in_deg");
        n.out_deg = integer(row.at("out_deg"), n.gid + ".out_deg");
        n.in_tx = integer(row.at("in_tx"), n.gid + ".in_tx");
        n.out_tx = integer(row.at("out_tx"), n.gid + ".out_tx");
        n.in_kzt = number(row.at("in_kzt"), n.gid + ".in_kzt");
        n.out_kzt = number(row.at("out_kzt"), n.gid + ".out_kzt");
        n.pagerank = number(row.at("pagerank"), n.gid + ".pagerank");
        if (n.pagerank > 1) fail(n.gid + ": pagerank exceeds 1");
        if (!source_nodes.emplace(n.gid, &row).second) fail("Duplicate gid: " + n.gid);
        if (row.contains("pass_through")) {
            if (n.in_kzt == 0) {
                if (!row.at("pass_through").is_null()) fail(n.gid + ": pass_through must be null when in_kzt=0");
            } else {
                const double ratio = n.out_kzt / n.in_kzt;
                if (!std::isfinite(ratio) || !close(number(row.at("pass_through"), "pass_through"), ratio))
                    fail(n.gid + ": inconsistent pass_through");
            }
        }
        if (row.contains("truncated_by_depth") &&
            boolean(row.at("truncated_by_depth"), "truncated_by_depth") != (n.depth == max_depth && n.out_deg == 0))
            fail(n.gid + ": inconsistent truncated_by_depth");
        nodes.push_back(std::move(n));
    }
    std::sort(nodes.begin(), nodes.end(), [](const Node& a, const Node& b) { return a.numeric_gid < b.numeric_gid; });
    for (std::size_t i = 0; i < nodes.size(); ++i) index.emplace(nodes[i].gid, i);

    std::vector<Edge> edges;
    std::set<std::pair<std::size_t, std::size_t>> pairs;
    for (const auto& row : input.at("edges")) {
        const auto src = identifier(row.at("src"), "edge.src");
        const auto dst = identifier(row.at("dst"), "edge.dst");
        if (!index.count(src) || !index.count(dst)) fail("Unknown edge endpoint: " + src + " -> " + dst);
        const auto s = index.at(src), d = index.at(dst);
        if (!pairs.emplace(s, d).second) fail("Duplicate edge: " + src + " -> " + dst);
        const double sum = number(row.at("sum_kzt"), "edge.sum_kzt");
        const auto count = integer(row.at("n_tx"), "edge.n_tx");
        if (sum <= 0 || count == 0) fail("Edge sum_kzt and n_tx must be positive");
        edges.push_back({s, d, sum, count});
    }
    std::sort(edges.begin(), edges.end(), [](const Edge& a, const Edge& b) {
        return std::tie(a.src, a.dst) < std::tie(b.src, b.dst);
    });
    std::vector<double> sum_in(nodes.size()), sum_out(nodes.size());
    std::vector<std::int64_t> tx_in(nodes.size()), tx_out(nodes.size());
    for (const auto& e : edges) {
        nodes[e.src].outgoing.push_back(e.dst);
        nodes[e.dst].incoming.push_back(e.src);
        sum_out[e.src] += e.sum;
        sum_in[e.dst] += e.sum;
        if (!std::isfinite(sum_out[e.src]) || !std::isfinite(sum_in[e.dst])) fail("Amount sum overflow");
        add_count(tx_out[e.src], e.count);
        add_count(tx_in[e.dst], e.count);
        if (e.src == e.dst) nodes[e.src].self_kzt = e.sum;
    }
    // Aggregation is for validation only; supplied Python features remain the baseline.
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        auto& n = nodes[i];
        if (static_cast<std::uint64_t>(n.in_deg) != n.incoming.size() ||
            static_cast<std::uint64_t>(n.out_deg) != n.outgoing.size() ||
            n.in_tx != tx_in[i] || n.out_tx != tx_out[i] ||
            !close(n.in_kzt, sum_in[i]) || !close(n.out_kzt, sum_out[i]))
            fail(n.gid + ": supplied node metrics disagree with edges");
        std::set<std::size_t> peers;
        std::set<std::int64_t> clusters;
        const auto inspect = [&](std::size_t other) {
            if (other == i) return;
            peers.insert(other);
            if (nodes[other].cluster != n.cluster) {
                clusters.insert(nodes[other].cluster);
                ++n.cross_edges;
            }
        };
        for (const auto other : n.incoming) {
            inspect(other);
            if (other != i) { ++n.nonself_in; if (nodes[other].seed) ++n.direct_seeds; }
        }
        for (const auto other : n.outgoing) { inspect(other); if (other != i) ++n.nonself_out; }
        n.peers = peers.size();
        n.external_clusters = clusters.size();
    }

    std::size_t seed_count = 0;
    std::vector<std::size_t> seen(nodes.size(), 0), queue;
    std::vector<std::int64_t> distance(nodes.size());
    queue.reserve(nodes.size());
    // One BFS per seed. A seed never counts itself, even when a cycle returns to it.
    for (std::size_t s = 0; s < nodes.size(); ++s) {
        if (!nodes[s].seed) continue;
        ++seed_count;
        queue.clear(); queue.push_back(s); seen[s] = seed_count; distance[s] = 0;
        for (std::size_t head = 0; head < queue.size(); ++head) {
            const auto v = queue[head];
            for (const auto next : nodes[v].outgoing) {
                if (seen[next] == seed_count) continue;
                seen[next] = seed_count;
                distance[next] = distance[v] + 1;
                ++nodes[next].seed_reach;
                if (nodes[next].min_hops < 0 || distance[next] < nodes[next].min_hops)
                    nodes[next].min_hops = distance[next];
                queue.push_back(next);
            }
        }
    }

    std::vector<double> in_values, out_values, volumes, peer_values;
    for (const auto& n : nodes) {
        in_values.push_back(std::max(0.0, n.in_kzt - n.self_kzt));
        out_values.push_back(std::max(0.0, n.out_kzt - n.self_kzt));
        volumes.push_back(std::max(in_values.back(), out_values.back()));
        peer_values.push_back(static_cast<double>(n.peers));
    }
    const auto in_pct = percentiles(in_values), out_pct = percentiles(out_values);
    const auto volume_pct = percentiles(volumes), peers_pct = percentiles(peer_values);
    json results = json::array();
    std::map<std::string, std::size_t> role_counts;
    for (std::size_t i = 0; i < nodes.size(); ++i) {
        const auto& n = nodes[i];
        const bool boundary = n.depth == max_depth;
        const double in = in_values[i], out = out_values[i];
        const double ratio = in > 0 ? out / in : 0;
        if (in > 0 && !std::isfinite(ratio)) fail(n.gid + ": pass-through overflow");
        const double in_degree = static_cast<double>(n.nonself_in);
        const double out_degree = static_cast<double>(n.nonself_out);
        const double reach = static_cast<double>(n.seed_reach);
        const double cluster_count = static_cast<double>(n.external_clusters);
        const double quality = (boundary ? cfg("boundary_role_multiplier") : 1.0) *
                               (n.seed ? cfg("seed_role_multiplier") : 1.0);
        json candidates = json::array();
        std::string evidence;
        const auto candidate = [&](const std::string& role, double score, const std::string& explanation) {
            candidates.push_back({{"role", role}, {"score", bounded(score * quality)}});
            if (candidates.size() == 1) evidence = explanation;
        };
        // Specific structural role wins before simpler flow roles. All matching
        // alternatives remain visible to the analyst in role_candidates.
        if (reach >= cfg("coordinator_min_seeds") && cluster_count >= cfg("coordinator_min_external_clusters") &&
            in_degree >= cfg("coordinator_min_senders") && out_degree >= cfg("coordinator_min_receivers") &&
            volume_pct[i] >= cfg("coordinator_min_volume_percentile")) {
            candidate("coordinator", 0.5 + 0.2 * saturation(reach, 2 * cfg("coordinator_min_seeds")) +
                0.15 * saturation(cluster_count, 2 * cfg("coordinator_min_external_clusters")) + 0.15 * volume_pct[i],
                u8"Гипотеза координации: достижим из " + std::to_string(n.seed_reach) + u8" seed; внешних кластеров " +
                std::to_string(n.external_clusters) + u8"; отправителей/получателей " + std::to_string(n.nonself_in) +
                "/" + std::to_string(n.nonself_out) + ".");
        }
        if (in_degree >= cfg("consolidator_min_senders") && in_degree > out_degree && in > 0 &&
            in_pct[i] >= cfg("consolidator_min_in_percentile")) {
            candidate("consolidator", 0.55 + 0.25 * saturation(in_degree, 2 * cfg("consolidator_min_senders")) + 0.2 * in_pct[i],
                u8"Признаки консолидации: " + std::to_string(n.nonself_in) + u8" отправителей; вход " + fmt(in) +
                u8" KZT; " + std::to_string(n.nonself_out) + u8" получателей.");
        }
        if (out_degree >= cfg("distributor_min_receivers") && out_degree > in_degree && out > 0 &&
            out_pct[i] >= cfg("distributor_min_out_percentile")) {
            candidate("distributor", 0.55 + 0.25 * saturation(out_degree, 2 * cfg("distributor_min_receivers")) + 0.2 * out_pct[i],
                u8"Признаки распределения: " + std::to_string(n.nonself_out) + u8" получателей; выход " + fmt(out) +
                u8" KZT; " + std::to_string(n.nonself_in) + u8" отправителей.");
        }
        if (!n.seed && !boundary && in_degree > 0 && out_degree > 0 && in > 0 &&
            ratio >= cfg("transit_ratio_min") && ratio <= cfg("transit_ratio_max")) {
            const double width = ratio < 1 ? 1 - cfg("transit_ratio_min") : cfg("transit_ratio_max") - 1;
            const double closeness = bounded(1 - std::abs(ratio - 1) / width);
            candidate("transit", 0.5 + 0.3 * closeness + 0.2 * std::min(in_pct[i], out_pct[i]),
                u8"Признаки транзита: вход " + fmt(in) + u8", выход " + fmt(out) + u8" KZT; выход/вход=" +
                fmt(ratio) + u8". Совпадение сумм не доказывает движение тех же денег.");
        }
        if (!n.seed && !boundary && in_degree > 0 && n.out_deg == 0 && in > 0) {
            candidate("terminal", std::min(0.8, 0.5 + 0.2 * in_pct[i] + 0.2 * saturation(in_degree, 3)),
                u8"Гипотеза конечного получателя: вход " + fmt(in) + u8" KZT от " + std::to_string(n.nonself_in) +
                u8"; исходящих 0; глубина " + std::to_string(n.depth) + u8". Только в пределах выгрузки.");
        }
        if (candidates.empty()) {
            candidate("peripheral", 0, u8"Недостаточно признаков роли: отправителей " + std::to_string(n.nonself_in) +
                u8", получателей " + std::to_string(n.nonself_out) + u8", достижим из " + std::to_string(n.seed_reach) + u8" seed.");
        }
        if (boundary) evidence += u8" Граница обхода; исходящие неполны.";
        if (n.seed) evidence += u8" Seed: входящие неполны.";
        json signals = {{"seed_reach", saturation(reach, cfg("priority_seed_saturation"))},
                        {"volume", volume_pct[i]}, {"counterparties", peers_pct[i]},
                        {"external_clusters", saturation(cluster_count, cfg("priority_cluster_saturation"))}};
        json breakdown = json::object();
        double priority = 0;
        for (const auto& item : signals.items()) {
            const double weight = config["priority_weights"][item.key()].get<double>();
            const double signal = item.value().get<double>();
            const double contribution = weight * signal;
            priority += contribution;
            breakdown[item.key()] = {{"signal", signal}, {"weight", weight}, {"contribution", contribution}};
        }
        const std::string why = u8"Приоритет проверки: достижим из " + std::to_string(n.seed_reach) +
            u8" seed; max(вход,выход)=" + fmt(volumes[i]) + u8" KZT; контрагентов " + std::to_string(n.peers) +
            u8"; внешних кластеров " + std::to_string(n.external_clusters) + ".";
        json warnings = json::array({"OBSERVED_SUBGRAPH_ONLY", "ROLE_IS_HYPOTHESIS"});
        if (boundary) warnings.push_back("OUTGOING_INCOMPLETE_AT_DEPTH_LIMIT");
        if (n.seed) warnings.push_back("SEED_INCOMING_INCOMPLETE");
        if (n.in_deg == 0 && n.out_deg == 0) warnings.push_back("NO_OBSERVED_EDGES");
        if (n.self_kzt > 0) warnings.push_back("SELF_TRANSFERS_EXCLUDED_FROM_ROLE_AND_PRIORITY");
        if (out > in) warnings.push_back("OBSERVED_OUTFLOW_EXCEEDS_INFLOW");
        const std::string role = candidates.front().at("role").get<std::string>();
        ++role_counts[role];
        results.push_back({{"gid", n.gid}, {"cluster_id", n.cluster}, {"role", role},
            {"role_score", candidates.front().at("score")}, {"priority_score", bounded(priority)},
            {"evidence", short_text(evidence)}, {"why", short_text(why)}, {"role_candidates", candidates},
            {"priority_breakdown", breakdown}, {"warnings", warnings},
            {"features", {{"seed_reach_count", n.seed_reach}, {"direct_seed_senders", n.direct_seeds},
                {"min_seed_hops", n.min_hops < 0 ? json(nullptr) : json(n.min_hops)},
                {"external_cluster_count", n.external_clusters}, {"cross_cluster_edges", n.cross_edges},
                {"counterparty_count", n.peers}, {"nonself_in_deg", n.nonself_in}, {"nonself_out_deg", n.nonself_out},
                {"observed_in_kzt", in}, {"observed_out_kzt", out},
                {"observed_pass_through", in > 0 ? json(ratio) : json(nullptr)},
                {"boundary_node", boundary}, {"truncated_by_depth", boundary && n.out_deg == 0},
                {"in_percentile", in_pct[i]}, {"out_percentile", out_pct[i]},
                {"volume_percentile", volume_pct[i]}, {"counterparty_percentile", peers_pct[i]}}}});
    }
    std::vector<std::size_t> order(nodes.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        return results[a]["priority_score"].get<double>() > results[b]["priority_score"].get<double>();
    });
    json top = json::array();
    for (std::size_t rank = 0; rank < std::min<std::size_t>(20, order.size()); ++rank) {
        const auto& row = results[order[rank]];
        top.push_back({{"rank", rank + 1}, {"gid", row["gid"]}, {"role", row["role"]},
            {"priority_score", row["priority_score"]}, {"why", row["why"]}});
    }
    return {{"schema_version", "1.0"}, {"engine_version", "1.0.0"}, {"nodes", results}, {"top_nodes", top},
        {"meta", {{"node_count", nodes.size()}, {"edge_count", edges.size()}, {"seed_count", seed_count},
            {"role_counts", role_counts}, {"config", config},
            {"role_score_semantics", "Heuristic rule strength, not calibrated probability"},
            {"priority_semantics", "Review priority, not probability of wrongdoing"},
            {"limitations", json::array({"Directed reachability is not proof of provenance or time-ordered money flow",
                "Only intrabank transfers >=5000 KZT in the observed month are available",
                "No full account balances; depth boundary and seed inflows are incomplete",
                "Clusters and rule thresholds are hypotheses, not labels of criminal organizations"})}}}};
}
} // namespace money_graph
