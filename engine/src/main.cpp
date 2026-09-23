#include "analysis.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using money_graph::json;

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
            std::cout << "Usage: engine input.json result.json [--config overrides.json]\n"
                         "       engine --print-config\n";
            return 0;
        }
        if (argc != 3 && !(argc == 5 && std::string(argv[3]) == "--config")) {
            std::cerr << "Usage: engine input.json result.json [--config overrides.json]\n";
            return 2;
        }
        const auto input_path = fs::u8path(argv[1]);
        const auto output_path = fs::u8path(argv[2]);
        if (fs::weakly_canonical(input_path) == fs::weakly_canonical(output_path) ||
            (fs::exists(output_path) && fs::equivalent(input_path, output_path))) {
            throw std::runtime_error("Input and output paths must differ");
        }
        const auto config = money_graph::configuration(
            argc == 5 ? read_json(fs::u8path(argv[4])) : json::object());
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
