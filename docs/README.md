# Документация

Начало работы и команды: [главный README](../README.md).
Исходные требования и материалы организаторов: [TechTask](../TechTask/README.md).

## Действующие инструкции

| Задача | Документ |
|---|---|
| Собрать C++, понять правила и пороги | [Ядро](../engine/README.md) |
| Подключить Python к C++ | [Контракт ядра](../engine/CONTRACT.md) |
| Подключить UI и выгрузки | [Общий контракт](../CONTRACT.md) |
| Запустить интерфейс | [Frontend](../frontend/README.md) |
| Проверить интерфейс на поставке 1.3.0 | [Приёмка UI](../frontend/RESILIENCE_CHECK.md) |
| Пройти демонстрацию | [Сценарий](../frontend/DEMO.md), [контрольные случаи](../team/DEMO_CASES.md) |
| Проверить пользовательский сценарий | [Протокол приёмки](../team/USABILITY_CHECK.md) |
| Найти текущее задание участника | [Команда](../team/README.md), [план до дедлайна](../team/LAST_80_MINUTES.md) |
| Реализовать структурный эксперимент | [Контракт устойчивости](../team/RESILIENCE_CONTRACT.md) |
| Проверить пользу и сравнить с отбором по обороту | [Измерения на 2248 клиентах](EVIDENCE.md) |
| Воспроизвести подготовку данных | [Команды Армана](../team/arman/REPRODUCIBILITY.md) |
| Проверить состав сторонних материалов | [THIRD_PARTY](../THIRD_PARTY.md) |

Код, исходные данные и пути запуска сохранены. Активные командные задания
остаются в `team/`, чтобы участники продолжали работу по переданным ссылкам.

## Архив проверок и завершённых задач

Архив хранит факты проверок конкретных коммитов. Старые числа тестов, версии,
замеры и незакрытые на тот момент пункты не описывают автоматически текущий HEAD.
Текущие команды и форматы берите из инструкций выше.

- **Ядро и интеграция:** [первичная проверка](archive/engine/VALIDATION.md),
  [интеграция 1.1–1.2](archive/engine/INTEGRATION.md),
  [сверка ТЗ](archive/engine/TZ_AUDIT.md),
  [проверка чистой копии](archive/engine/CLEAN_CHECK.md).
- **Интерфейс:** [история браузерных проверок](archive/frontend/VERIFICATION.md),
  [история сверок с Word](archive/frontend/WORD_TZ_CHECK.md).
- **Команда:** [технические критерии и проверка fbec33f](archive/team/TECHNICAL_REVIEW.md),
  [внутренняя оценка fbec33f](archive/team/CURRENT_REVIEW.md),
  [прежний план](archive/team/FINISH_PLAN.md),
  [первый план интеграции UI](archive/team/NEXT_STEPS.md),
  [этапы Артура](archive/team/Artur.md),
  [передача next_actions](archive/team/artur/NEXT_ACTIONS.md).

Отчёт воспроизводимости Армана пока остаётся в его рабочей папке:
[FINAL_RUN.md](../team/arman/FINAL_RUN.md).
Машинные отчёты прежних версий ядра лежат рядом с их описаниями в
[`archive/engine/reports/`](archive/engine/reports/).
