# Воспроизводимость данных и интеграции

Актуальная проверка версии с интерфейсом и optional `next_actions`:
[FINAL_RUN.md](FINAL_RUN.md). Ниже сохранены ранний прогон `c7f7bb4`
и инструкция для другого физического ноутбука.

23 сентября 2026 года проверено tracked-состояние
`c7f7bb4a7b166c2580312ff9f41a9136186ef54c` в новой копии исходников,
с отдельным Python venv и новой Release-сборкой C++ 1.1.0.
Оба полных пересчёта прошли: **7.449 и 3.432 секунды**.

## Что именно подтверждено

| Проверка | Статус и граница вывода |
|---|---|
| Новая копия tracked HEAD | Выполнено через `git archive`; исходные `.venv`, `engine/build`, `out` не копировались |
| Изоляция Python | Новый venv, `include-system-site-packages=false`, установка `requirements.txt` с нуля в этот venv |
| Сборка C++ | Новая CMake Release-сборка в чистой копии, встроенная nlohmann/json из репозитория |
| Полный пересчёт | Настоящий C++ 1.1.0, два запуска от исходных Parquet до CSV/JSON |
| Повторяемость артефактов | input.json, result.json, graph.json, три CSV и validation.json совпали побайтово |
| Manifest | Все записанные SHA-256 проверены по фактическим файлам |
| Другой физический ноутбук | **Ещё не выполнено.** Проверка выше шла на том же ноутбуке |
| Общие ресурсы среды | Использовались существующие Python runtime, переносимые CMake/Ninja/Zig, сетевой доступ, pip-кэш и кэш Zig |
| Проверка интерфейса | Не выполнена: исходников UI на проверенном коммите нет |

Чистый venv исключает зависимость от пакетов рабочей среды, но не заменяет
командный запуск на другом ноутбуке. Такой запуск остаётся отдельным шагом
приёмки ниже.

## Фактическая среда и время

| Компонент | Версия |
|---|---|
| ОС | Windows NT 10.0.26200.0, x86_64 |
| Python | 3.12.14 |
| CMake | 4.4.3 |
| Ninja | 1.13.2.git.kitware.jobserver-pipe-1 |
| Компилятор | Zig 0.13.0 / clang 18.1.6, target x86_64-windows-gnu |
| NumPy / pandas / PyArrow | 2.5.3 / 3.0.1 / 25.0.1 |
| NetworkX / SciPy / jsonschema | 3.7 / 1.18.1 / 4.26.0 |

`pip check` завершился без конфликтов зависимостей.

| Этап | Wall time, секунд |
|---|---:|
| Создание venv | 10.909 |
| Установка requirements.txt | 96.266 |
| CMake configure Release | 4.242 |
| CMake build Release | 13.199 |
| 28 тестов C++ | 2.517 |
| Первый `python pipeline.py --out out` | 7.449 |
| Повторный `python pipeline.py --out out-repeat` | 3.432 |

Полное время измерено внешним `time.perf_counter()` вокруг subprocess, включая
старт Python и импорт библиотек. Установка и компиляция выполняются до отсчёта
лимита 300 секунд на пересчёт. Более быстрый второй запуск согласуется с
прогретыми файловыми/системными кэшами; фиксированный runtime не гарантируется.

## Проверенный набор

Получены 2248 клиентов, 3119 направленных связей и 4840 транзакций; среди клиентов
81 seed, включая все 19 изолированных seed. Выделены 88 кластеров, сформирован
топ-20. `graph.meta.is_demo=false`, все gid в JSON — строки.

CSV содержат соответственно 2248 / 88 / 20 строк данных и обязательные колонки.
nodes_roles.csv покрывает все узлы графа. validation.json содержит `ok=true`.
Сумма переводов — 365890012.01 KZT; максимальное расхождение агрегата по паре —
5.820766091346741e-11 KZT при допуске 0.01 KZT. Сохранены 97 одинаковых строк
транзакций: без transaction_id они не считаются доказанными дубликатами.

Контрольные SHA-256 для указанного коммита и окружения:

| Файл | SHA-256 |
|---|---|
| input.json | `7e4633961e9323598545cda919c4130c07faff9e296bd50c94442dc75753d946` |
| result.json | `608d9cd24a1ac14a0c3e87ea977fc401c072b99aaee79629d512c1ef3d00e0a8` |
| graph.json | `0feac3b3d9e78df3a314116eefc96ec82b6d1b0bd251ab2653fd86e477adc95a` |
| nodes_roles.csv | `5168ac63bf3a8f7dfe15aa3e807d6b2a68e0602fbdacc5777ff6c1c08c74bae8` |
| clusters.csv | `ad763398ba39f1bf222cf8273abf70cbe6d6a69d49f5781968e691b209d3afe6` |
| top_nodes.csv | `52cf299c058c6c5b6dc917aefbc63e55092ded866f07512aedf239a2587423b0` |
| validation.json | `a65750317d677497f336b047332a19bab5713e19f75d82fde7c52900c239b31b` |

run_manifest.json включает время и хэш конкретного бинарника, поэтому между
запусками/компиляторами не обязан совпадать побайтово. После изменения кода,
входных данных или зависимостей следует сформировать новый согласованный набор
и проверить его собственный manifest; приведённые хэши относятся к c7f7bb4.

## Командный запуск на втором ноутбуке — ещё не выполнен

Нужны Git, Python 3.12, CMake >=3.16 и доступный C++17-компилятор.
Установку Python-пакетов выполнить до демонстрации. Сборка C++ и пересчёт
не требуют внешнего сервиса; JSON-библиотека включена в репозиторий.

### Windows PowerShell

Открыть терминал с настроенным компилятором, например Developer PowerShell для
Visual Studio с установленным компонентом C++. После `git clone` перейти в корень:

```powershell
git clone https://github.com/BAITC-Hacks/hack-5886f2d6-talents.git
cd hack-5886f2d6-talents
git rev-parse HEAD
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --config Release --parallel 2
.\.venv\Scripts\python.exe prepare_ui_data.py
.\.venv\Scripts\python.exe verify_outputs.py
```

Явный вызов Python из venv не требует изменения политики PowerShell или запуска
Activate.ps1. Альтернатива сборки для установленного CLion:
`powershell -ExecutionPolicy Bypass -File engine/build.ps1`.
Пайплайн автоматически находит стандартный путь бинарника, в том числе
`engine/build/Release/engine.exe` при Visual Studio.

### Linux/macOS

```sh
git clone https://github.com/BAITC-Hacks/hack-5886f2d6-talents.git
cd hack-5886f2d6-talents
git rev-parse HEAD
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --config Release --parallel 2
.venv/bin/python prepare_ui_data.py
.venv/bin/python verify_outputs.py
```

`prepare_ui_data.py` выполняет расчёт и готовит статические данные для UI в
`frontend/public/data`; `verify_outputs.py` проверяет согласованность комплекта.
Эти команды доставки добавлены после проверенного c7f7bb4. Замеры выше относятся
к прямому `pipeline.py`, а не к ещё не проведённому запуску на втором ноутбуке.

Предлагаемые URL интерфейса: `/data/graph.json`, `/data/nodes_roles.csv`,
`/data/clusters.csv`, `/data/top_nodes.csv`. Наличие каталога public/data само
по себе не означает, что UI реализован. Команда запуска UI будет добавлена
после первого коммита Савелия.

После второго ноутбука участник команды фиксирует в этом документе: имя участника,
дату, commit SHA, ОС/версии, фактические команды, wall time, статус проверок,
счётчики файлов и `meta.is_demo=false`. До этого статус шага остаётся невыполненным.

## Границы аналитических выводов

Depth=4 — граница наблюдения; входящие seed неполны. Louvain использует
неориентированную проекцию с суммированием встречных весов, seed=42 и
resolution=1.0; изолированные получают собственные кластеры. Внутренняя сумма —
оборот исходных направленных рёбер внутри сообщества, не остаток средств.
Роли, приоритет и сообщества являются гипотезами для проверки аналитиком.
