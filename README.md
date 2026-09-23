# hack-5886f2d6-talents
Hackathon team repository for TALENTS

## Аналитическое ядро C++ — Артур

Реализация находится в [`engine/`](engine/README.md).

- [Контракт для Python-пайплайна](engine/CONTRACT.md)
- [Пример input.json](engine/examples/input.json)
- [Пример result.json](engine/examples/result.json)
- [Пороговые значения и веса](engine/config/default.json)
- [Проверка на данных организаторов](engine/VALIDATION.md)

```sh
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --config Release --parallel 2
```

Запуск: `engine input.json result.json`. На Windows с MinGW собранная программа —
`engine/build/engine.exe`, с Visual Studio — `engine/build/Release/engine.exe`.
Также доступен `engine/build.ps1`, который находит инструменты установленного CLion.

Данные, ТЗ и оригинальный стартер организаторов находятся в `TechTask/`.

## Материалы для тиммейтов

- [Арман: данные и интеграция](team/arman/README.md)
- [Савелий: интерфейс](team/saveliy/README.md)
- [Демонстрационный graph.json для интерфейса](team/saveliy/graph.example.json)
