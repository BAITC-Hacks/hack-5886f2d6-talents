# Интеграционный контракт v1

Python адаптирован к существующему [контракту C++ Артура](engine/CONTRACT.md). Схемы в engine/schemas — источник истины для обмена с движком. Этот файл уточняет экспорт Python и формат интерфейса.

## Python → C++

Вызов без shell: `engine input.json result.json [--config overrides.json]`. Пути абсолютные, передаются отдельными аргументами. JSON UTF-8, schema_version="1.0". Узел содержит плоские gid, depth, is_seed, cluster_id, in_deg, out_deg, in_kzt, out_kzt, in_tx, out_tx, pagerank, pass_through, truncated_by_depth. Копия метрик в `metrics`, дополнительные признаки и объект `flags` разрешены как дополнительные поля; ядру они не нужны.

gid/src/dst — каноническая десятичная строка signed int64, без ведущих нулей и плюса. Нельзя преобразовывать во float. NaN/Infinity запрещены; неопределённый pass_through — null.

Рёбра направленные: src, dst, sum_kzt, n_tx, depth; одна запись на упорядоченную пару. Все узлы, включая изолированные, передаются ядру.

## C++ → Python

Корень: schema_version, engine_version, nodes, top_nodes, meta. Каждый узел содержит gid, cluster_id, role, role_score, priority_score, evidence, why, features, role_candidates, priority_breakdown, warnings. Полный перечень типов: [result.schema.json](engine/schemas/result.schema.json).

Python проверяет схему, полный набор уникальных gid, неизменность cluster_id и топ-20. Объединение по gid; позиции массивов значения не имеют. Роли, оценки и объяснения C++ сохраняются без пересчёта и округления. Для более длинного топа Python сортирует все результаты по priority_score убыванию и числовому gid возрастанию.

## graph.json → Савелию

Корень: schema_version, meta, nodes, edges, clusters, top_nodes.

- nodes: плоские поля входа + проверенные поля C++ по gid, включая features, role_candidates, priority_breakdown, warnings. Дополнительные metrics/flags сохраняются для совместимости; UI использует плоские поля.
- edges: исходные направленные рёбра + `id=src+":"+dst`. Для Cytoscape преобразовать src/dst в source/target, сохраняя строковый тип.
- clusters: cluster_id, n_nodes, n_seed, sum_kzt_internal, top_gids (массив строк, до 5 лидеров), hypothesis.
- top_nodes: rank, gid, role, priority_score, why. Равные приоритеты упорядочиваются по числовому gid. На полном датасете минимум 20.
- meta: сведения Python и ядра, `engine=cpp-<engine_version>`, `engine_version`, `config`, `is_demo=false` для реального прогона. Полная исходная meta ядра дополнительно сохранена в engine_meta. Ограничения Python — в limitations.

Для Python-demo: engine=python-demo-v1, is_demo=true. Синтетические примеры также всегда имеют is_demo=true, даже если для них запускался настоящий C++. Поле demo — совместимый с ранним прототипом дубль индикатора. UI должен явно показывать демонстрационный режим.

Исходные in/out_kzt включают петли; features.observed_* ядра их исключают. Не смешивать эти показатели в одной подписи. role_score — сила признаков роли, priority_score — приоритет проверки. Все выводы — гипотезы.

## CSV и кластеры

Ровно обязательные колонки ТЗ, UTF-8, запятая, стандартное экранирование. top_gids в clusters.csv — JSON-массив строк внутри ячейки. gid записывается без .0; читать как строку.

Louvain: вес суммы двух направлений, исключение петель только из проекции, отдельные кластеры изолированных, seed=42, resolution=1.0. Номера кластеров по минимальному строковому gid. Внутренний оборот считается по исходным направленным рёбрам один раз.

## Примеры и передача

engine/examples — канонические примеры автора ядра. examples/input.json, result.json и graph.json — маленький синтетический прогон Python-интеграции; пересоздание: `python make_examples.py --core engine/build/engine.exe`. Без C++ доступен явный `--demo`.

Полный прогон: `python pipeline.py --out out`. Для интерфейса можно указать `--out frontend/public/data`, если этот каталог согласован с Савелием. Подтверждение UI-пути ещё не получено. Контракт C++ принят из кода Артура, но это не означает отдельного устного подтверждения команды.
