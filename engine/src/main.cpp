#include "analysis.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using money_graph::json;

const char* usage = "Usage: engine input.json result.json [--config overrides.json]\n"
                    "       engine --input input.json --output result.json [--config overrides.json]\n"
                    "       engine --print-config\n";

struct Arguments {
    std::string input, output, config;
};

Arguments parse_arguments(int argc, char** argv) {
    Arguments args;
    std::vector<std::string> positional;
    for (int i = 1; i < argc; ++i) {
        const std::string token = argv[i];
        if (token == "--input" || token == "--output" || token == "--config") {
            auto& target = token == "--input" ? args.input : token == "--output" ? args.output : args.config;
            if (!target.empty()) throw std::invalid_argument("Duplicate option: " + token);
            if (i + 1 >= argc || std::string(argv[i + 1]).rfind("--", 0) == 0 || std::string(argv[i + 1]).empty())
                throw std::invalid_argument("Missing value for " + token);
            target = argv[++i];
        } else if (token.rfind("--", 0) == 0) {
            throw std::invalid_argument("Unknown option: " + token);
        } else positional.push_back(token);
    }
    if (!positional.empty()) {
        if (positional.size() != 2 || !args.input.empty() || !args.output.empty())
            throw std::invalid_argument("Use either two positional paths or --input/--output");
        args.input = positional[0];
        args.output = positional[1];
    }
    if (args.input.empty() || args.output.empty()) throw std::invalid_argument("Input and output are required");
    return args;
}

json read_json(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("Cannot read file: " + path.u8string());
    // parse() consumes the whole document, so trailing garbage is rejected too.
    return json::parse(stream);
}

int run(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--print-config") {
            std::cout << money_graph::configuration().dump(2) << '\n';
            return 0;
        }
        if (argc == 2 && std::string(argv[1]) == "--help") {
            std::cout << usage;
            return 0;
        }
        Arguments args;
        try {
            args = parse_arguments(argc, argv);
        } catch (const std::invalid_argument& error) {
            std::cerr << "engine: " << error.what() << '\n' << usage;
            return 2;
        }
        const auto input_path = fs::u8path(args.input);
        const auto output_path = fs::u8path(args.output);
        if (fs::weakly_canonical(input_path) == fs::weakly_canonical(output_path) ||
            (fs::exists(output_path) && fs::equivalent(input_path, output_path))) {
            throw std::runtime_error("Input and output paths must differ");
        }
        const auto config = money_graph::configuration(
            !args.config.empty() ? read_json(fs::u8path(args.config)) : json::object());
        const auto result = money_graph::analyze(read_json(input_path), config);
        const auto serialized = result.dump(2); // Validate UTF-8 before touching output.
        if (output_path.has_parent_path()) fs::create_directories(output_path.parent_path());
        std::ofstream output(output_path, std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("Cannot open output: " + output_path.u8string());
        output << serialized << '\n';
        output.close();
        if (!output) throw std::runtime_error("Failed to write output: " + output_path.u8string());
        std::cerr << "Analyzed " << result.at("nodes").size() << " nodes; wrote "
                  << output_path.u8string() << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "engine: " << error.what() << '\n';
        return 1;
    }
}

#ifdef _WIN32
int wmain(int argc, wchar_t** argv) {
    std::vector<std::string> arguments;
    for (int i = 0; i < argc; ++i) arguments.push_back(fs::path(argv[i]).u8string());
    std::vector<char*> pointers;
    for (auto& argument : arguments) pointers.push_back(argument.data());
    return run(argc, pointers.data());
}
#else
int main(int argc, char** argv) { return run(argc, argv); }
#endif
