# 36 приёмочных кейсов Нурбола на моём билде — результат

**Дата:** 02.11.2026 · **Пакет:** `Abu_Nurbol_tests_for_Arman.zip` · **Запуск:** `team_suite.py` с `FBT_APP`

## Что было в пакете

| Файл | Назначение |
|---|---|
| `team_suite.py` | 36 кейсов, уже переведённых на `core.services.BudgetService` (16 functional, 14 integration, 6 UAT) |
| `cases.py`, `run_suite.py`, `service.py`, `db.py`, `defects.py` | Его reference build и 31 исходный кейс — для истории |
| `pg_contract_check.py`, `alibek_schema.sql`, `pg_contract_report.json` | Офлайн-сверка дампа Алибека с контрактом |
| `pg_handoff_ru.md` | Готовый текст для Алибека с DDL |

## Результат

```
python team_suite.py        (FBT_APP = путь к моему репозиторию)

до фикса:  Functional 16/16 · Integration 13/14 · UAT 6/6  → 35/36
после:     Functional 16/16 · Integration 14/14 · UAT 6/6  → 36/36
```

Важная оговорка: **UAT-блок читает `out/team_ui_results.json`** — файл, который Нурбол
положил в архив со своего UI-прогона. Сам я его не перезапускал: для этого нужен Streamlit,
которого в моей среде нет. Если убрать этот файл, судьба UAT видна честно:

```
Functional 16/16 · Integration 14/14 · UAT 1/6 · 5 not run
```

То есть **30 из 30 сервисных кейсов проходят**, а 5 UAT-кейсов ждут прогона на машине
со Streamlit (`python ui_check.py`).

## Найденный дефект: TC-T-29

Кейс: деактивировать участника, затем попробовать записать расход его «старым» объектом.

До фикса: запись проходила. Причина — сервис доверял словарю пользователя, который ему
передали. В словаре `is_active = 1`, а в базе уже `0`. В интерфейсе это не проявлялось,
потому что экран перечитывает пользователя на каждом rerun, но сервис — документированная
граница, и полагаться на память вызывающего нельзя.

**Фикс** (`core/services.py`): перед каждой записью пользователь перечитывается из базы.

```python
def _fresh(self, actor):
    row = self.db.query_one(
        "SELECT id, family_id, role, is_active, full_name FROM users WHERE id = ?", (int(actor["id"]),))
    if not row:
        raise AccessDenied("This account no longer exists.")
    if not int(row["is_active"]):
        raise AccessDenied("This account has been deactivated. Ask the family admin.")
    return dict(row)
```

Применено к `add_transaction`, `delete_transaction` и всем админским операциям
(`_require_admin` теперь тоже возвращает свежую запись). Роль и `family_id` берутся из базы,
а не из переданного объекта — заодно закрывает подделку словаря.

Регрессионный тест добавлен: `test_deactivated_member_cannot_write_with_a_stale_object`.
Всего тестов теперь **34**.

## Проверка после фикса

| Набор | Результат |
|---|---|
| Мои unit-тесты | 34/34 |
| `selfcheck.py` | 10/10 |
| `tools/abu_cases.py` (31 его кейс из отчёта) | 30 pass, 1 N/A, 0 fail |
| `tools/abu_conformance.py` (9 дефектов) | 9/9 закрыты |
| `team_suite.py` (его 36 кейсов) | 30/30 сервисных, UAT — его файл |

## Про PostgreSQL

Его `pg_contract_check.py` пришёл к тому же выводу, что и мой разбор: дамп Алибека контракт
не проходит (нет `families`, `numeric` вместо тиынов, `password` вместо `password_hash`,
`'Income'/'Expense'` вместо строчных, нет индексов). Два независимых разбора совпали —
это хороший аргумент на встрече.

`pg_handoff_ru.md` предлагает вариант A (ALTER-миграцию его дампа). Мой вариант B
(`tools/import_alibek.py` + `SETUP_POSTGRES.bat`) переносит данные без изменения его схемы.
Оба варианта ведут к одному контракту, выбирать команде.

## Как воспроизвести

```bat
set FBT_APP=C:\path\to\Family_Budget_Tracker_Arman
cd C:\path\to\Abu_Nurbol_tests_for_Arman
python team_suite.py
```

Результат пишется в `out/team_results.json`.


---

## Обновление 12:20 — пакет №2

Во втором архиве добавился `acceptance_10_rows_ru.md` — 10 приёмочных строк по экранам
(вход, дашборд, добавление, история, роли), все **PASS на v1.1**. Сам `team_suite.py`
не изменился (хеш совпадает), повторный прогон на текущей сборке: **36/36 PASS**.

Строки полезны для отчёта: они закрывают то, чего нет в сервисных кейсах — что интерфейс
действительно показывает правильные числа, а не только что сервис их возвращает.
