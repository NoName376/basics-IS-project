# Публичная ссылка на приложение

Два пути: быстрый (на сегодня) и постоянный (на защиту).

---

## Путь A — туннель Cloudflare, 2 минуты

Приложение работает локально, Cloudflare даёт ему публичный адрес.

1. Запусти `START.bat` (приложение на `http://localhost:8501`).
2. Двойной клик по **`TUNNEL.bat`**.
3. В окне появится строка вида:

   ```
   https://lung-creative-owns-asn.trycloudflare.com
   ```

   Это и есть публичная ссылка — открывается с телефона и любого ноутбука.

**Ограничения, о которых надо знать:**

- ссылка живёт, пока открыты **оба** окна: приложение и туннель;
- при каждом запуске адрес **новый** (бесплатный туннель без аккаунта);
- ноутбук должен быть включён и в интернете;
- ссылка публичная: любой, кто её знает, увидит экран входа. Данные закрыты паролем, но для реального продукта так нельзя.

Первый запуск `TUNNEL.bat` скачивает `tools\cloudflared.exe` (~55 МБ).

---

## Путь B — Streamlit Community Cloud, 10 минут, постоянная ссылка

Бесплатно, адрес не меняется, ноутбук можно выключать.

### 1. Выложить код на GitHub

```bat
cd /d D:\FamilyBudgetTracker\Family_Budget_Tracker_Arman
git init
git add .
git commit -m "Family Budget Tracker"
```

Создать пустой репозиторий на github.com и выполнить:

```bat
git remote add origin https://github.com/ТВОЙ_АККАУНТ/family-budget-tracker.git
git branch -M main
git push -u origin main
```

`.gitignore` уже исключает `postgres_url.txt`, `data/` и `cloudflared.exe` — секреты в репозиторий не попадут.

### 2. Подключить приложение

1. Зайти на **share.streamlit.io** через GitHub.
2. **New app** → выбрать репозиторий, ветку `main`, файл `app.py`.
3. **Advanced settings → Secrets** и вставить:

   ```toml
   DATABASE_URL = "postgresql://postgres.tzguuiwwxumhhiapqtsb:Alibek2006.%2C%3F@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"
   ```

4. **Deploy**.

`app.py` уже умеет читать `DATABASE_URL` из `st.secrets` — отдельная правка не нужна.

### 3. Проверить

Открыть выданную ссылку `https://….streamlit.app`, войти как `alibek@mail.com` / `alibek12345`.
В сайдбаре должно быть **Backend: PostgreSQL**.

---

## Что говорить преподавателю

> «Приложение развёрнуто и доступно по публичной ссылке. База — облачная PostgreSQL (Supabase), приложение подключается к ней по строке из секретов, пароли в репозитории не хранятся. Быстрый стенд поднят через туннель Cloudflare, постоянный — на Streamlit Community Cloud.»

---

## Если что-то не так

| Симптом | Причина |
|---|---|
| Туннель запустился, но ссылка не открывается | приложение не запущено или упало — проверь окно `START.bat` |
| `Backend: SQLite` на облаке | секрет `DATABASE_URL` не добавлен или в нём опечатка |
| `tenant not found` | неверный project-ref в строке подключения |
| Ошибка `psycopg2` | на Streamlit Cloud он ставится из `requirements.txt` автоматически; проверь логи приложения |
