# Арман — данные и интеграция

Последняя доработка: Python-проверки `meta.resilience`, независимый эталон
NetworkX и ограниченный retry публикации реализованы. Проверки и фактические
числа полного датасета: [RESILIENCE_CHECK.md](RESILIENCE_CHECK.md).
Приёмка общего пакета 1.3.0 ожидает публикации нового C++ и UI.

Задача с 16:40: [проверка устойчивости и надёжная публикация](LAST_80_MINUTES.md),
исходники до 17:10, общий пакет до 17:25.

Задачи из [FINISH_PLAN.md](../../docs/archive/team/FINISH_PLAN.md), пункты 1–2:

- Чистый запуск последней версии с UI и повтор затронутых проверок после изменений:
  [отчёт, команды и время](FINAL_RUN.md).
- Подключён C++ 1.2.0; полный пакет с `next_actions` опубликован в `859b33f`:
  [контракт, пример и следующие действия команды](NEXT_ACTIONS.md).
  Пройдены 110 Python-тестов; три CSV и ранжирование не меняются.

`prepare_ui_data.py` выполнен новым ядром: все 2248 списков действий сохранены
в graph.json, пакет проверен. Старый результат без поля тоже принимается.
UI Савелия с показом действий и карточкой связи подключён в `9a2ab3e`.
[Точный контракт и контрольные gid](../../docs/archive/team/artur/NEXT_ACTIONS.md).

Твой коммит `4a9c671` загружен и проверен вместе с C++:
[отчёт полного аудита](../../docs/archive/engine/TZ_AUDIT.md), 78 Python-тестов и 28 тестов ядра.
Уточнены гипотезы назначения кластеров; усилены проверки целых CSV-полей
и пустых hypothesis. Схемы и оценки не менялись, полный пакет пересчитан.

Текущий результат доставки: [`frontend/public/data/`](../../frontend/public/data/), настоящий C++ 1.2.0. Команда пересчёта с проверкой — `python prepare_ui_data.py`; проверка существующего комплекта — `python verify_outputs.py`. Подготовлены [материалы защиты](DATA_AND_CLUSTERS.md) и [инструкция для второго ноутбука с результатом ранней чистой проверки](REPRODUCIBILITY.md). UI Савелия уже включён в frontend и загружает проверяемый по manifest комплект `/data/*`.

Обновление после получения твоего коммита `ad6b1d5`: C++ 1.1.0 совместим
с позиционным запуском и плоскими метриками. Совместный прогон прошёл за 3.114 секунды,
потери полей для UI устранены. Результаты — в
[engine/INTEGRATION.md](../../docs/archive/engine/INTEGRATION.md).
Актуальные следующие задачи — [team/NEXT_STEPS.md](../../docs/archive/team/NEXT_STEPS.md).
Ниже сохранена справка по уже реализованной части и её контрактам.

Ты отвечаешь за Python-пайплайн: сырые Parquet → метрики и кластеры → C++-ядро
Артура → три CSV и данные для интерфейса Савелия. На хакатон выделено 5 часов.
Ядро уже реализовано; основной контракт описан в
[engine/CONTRACT.md](../../engine/CONTRACT.md).

## Что уже готово у Артура

- Исполняемая программа `engine input.json result.json`.
- Дополнительные признаки: достижимость из seed, ближайший seed по числу шагов,
  непосредственные seed-отправители, контрагенты и связи между кластерами.
- Шесть ролей, role_score, priority_score, evidence и why.
- Альтернативные подходящие роли, ограничения данных и вклады в приоритет.
- Топ-20, конфигурация правил и валидация входа.

Код: [engine/src](../../engine/src). Правила и сборка:
[engine/README.md](../../engine/README.md). Контрольный прогон всех 2248 клиентов
прошёл; [результаты проверки](../../docs/archive/engine/VALIDATION.md).

## Реализованный объём и справка по пайплайну

1. Использовать `TechTask/starter(1)/starter/starter.py` как основу. Данные находятся
   в `TechTask/data(1)/data/`.
2. Проверить уникальность gid и пар src→dst, существование концов рёбер,
   совпадение сумм и количества транзакций с агрегированными edges.
3. Добавить в граф все узлы из nodes.parquet, включая 19 изолированных.
4. Рассчитать базовые метрики стартера. Для PageRank через NetworkX нужен SciPy:
   его нет в исходном requirements.txt организаторов, поэтому добавь зависимость.
5. Выполнить Louvain с фиксированным seed. На неориентированной проекции суммировать
   встречные рёбра явно: простой `to_undirected()` может потерять один из весов.
   Назначить cluster_id каждому узлу, включая изолированные.
6. Сформировать input.json, вызвать ядро, проверить код выхода и состав результата.
7. Объединить результат с исходными метриками по gid, сохранить три CSV и graph.json.
8. Обеспечить полный запуск одной командой, указать зависимости и команды в README.

## Вход и выход C++

На входе корневой объект `{"schema_version":"1.0","nodes":[],"edges":[]}`.

Каждый узел обязательно содержит:

```text
gid: string
depth: integer
is_seed: boolean
cluster_id: integer >= 0
in_deg, out_deg, in_tx, out_tx: integer >= 0
in_kzt, out_kzt: number >= 0
pagerank: number от 0 до 1
```

Ребро: `src`, `dst` — строки; `sum_kzt` — положительное число;
`n_tx` — положительное целое. Дополнительные поля разрешены.
`pass_through` можно опустить либо передать число/null; `truncated_by_depth`
можно опустить либо передать согласованный boolean.

Все gid сохраняй строками от чтения исходного int64 до записи JSON, включая
src и dst. Не используй промежуточное преобразование во float или pandas.iterrows()
на смешанных числовых строках: идентификатор может потерять точность.

Канонические примеры и схемы:

- [input.json](../../engine/examples/input.json)
- [result.json](../../engine/examples/result.json)
- [input.schema.json](../../engine/schemas/input.schema.json)
- [result.schema.json](../../engine/schemas/result.schema.json)

Сборка из корня репозитория:

```sh
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build --config Release --parallel 2
```

На Windows можно запустить `powershell -ExecutionPolicy Bypass -File engine/build.ps1`.
Путь программы: MinGW/Ninja — `engine/build/engine.exe`, Visual Studio —
`engine/build/Release/engine.exe`, Linux/macOS — `engine/build/engine`.
Библиотека JSON уже в репозитории; дополнительные C++-пакеты скачивать не нужно.

```python
import json
import subprocess
from pathlib import Path

# engine_path, input_path, result_path — выбранные вашим пайплайном Path.
input_path.write_text(
    json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8"
)
subprocess.run(
    [str(engine_path.resolve()), str(input_path.resolve()), str(result_path.resolve())],
    check=True,
)
result = json.loads(result_path.read_text(encoding="utf-8"))
```

Перед сериализацией замени отсутствующие числовые значения pandas на None:
NaN/Infinity не входят в JSON-контракт. После запуска объединяй таблицы по gid,
а не по позиции строк, например через `merge(..., validate="one_to_one")`.
Проверяй, что наборы gid совпадают и нет пропущенных ролей.

## Обязательные CSV

| Файл | Колонки |
|---|---|
| nodes_roles.csv | gid, role, role_score, cluster_id, priority_score, evidence |
| clusters.csv | cluster_id, n_nodes, n_seed, sum_kzt_internal, top_gids, hypothesis |
| top_nodes.csv | rank, gid, role, priority_score, why |

В nodes_roles.csv должны быть все узлы; в top_nodes.csv — минимум 20 на полном
датасете. Ядро уже возвращает `top_nodes` и все оценки. `clusters.csv` формируешь
ты: внутренний оборот — сумма исходных направленных рёбер, у которых оба конца
в кластере; каждое ребро учитывается один раз. Для top_gids выберите и опишите
стабильный формат CSV-ячейки, например JSON-массив строк. Гипотезы кластеров
формулируйте из фактических метрик, без утверждений о виновности.

В CSV gid можно записать как исходный int64 через `int(gid_string)`. В JSON
идентификаторы всегда остаются строками.

## Передача данных Савелию

В [папке Савелия](../saveliy/README.md) описан предлагаемый формат graph.json,
а [graph.example.json](../saveliy/graph.example.json) позволяет ему сразу делать экран.
Этот формат реализован в текущем экспорте Python и описан также в корневом CONTRACT.md.

Предлагаемая сборка graph.json:

- `nodes`: исходная строка узла с метриками + строка результата C++, соединённые по gid;
- `edges`: исходные направленные рёбра с добавленным `id = src + ":" + dst`;
- `top_nodes`: массив результата C++;
- `clusters`: строки сводки кластеров; top_gids здесь массив строк;
- `meta`: метаданные C++ и `is_demo=false` для настоящего датасета;
- `schema_version`: `"1.0"`.

Общие gid/cluster_id в двух источниках должны совпадать до объединения.
В итоговом UI-узле сохраняются и исходные метрики, и `features`, `warnings`,
`priority_breakdown`. CSV положите рядом с graph.json в согласованную статическую
папку интерфейса; конкретный путь согласуйте с Савелием.

## Что можно взять для ускорения

[engine/tests/check_dataset.py](../../engine/tests/check_dataset.py) уже показывает
загрузку стартера, проверку данных, подготовку входа и вызов ядра. Это тестовый
адаптер, он не создаёт обязательные CSV или полноценный production-пайплайн.
Используй его как рабочий пример и дополни своей частью.

Критичные ограничения: depth=4 не доказывает terminal, входящие seed неполны,
role_score не является вероятностью, исходные суммы не являются остатками счёта.
Не меняй роли и приоритеты после C++ без согласованного изменения правил.

Цель интеграции: примерно к середине хакатона получить полный прогон от настоящих
Parquet до файлов, которые открывает интерфейс. Последний час оставить на
README, чистый запуск и репетицию демонстрации.
