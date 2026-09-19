# Notion Tasks Bot

Личный Telegram-бот для базы Notion «Задачи и дедлайны»: списки задач, смена статусов,
добавление задач свободным текстом (через LLM), утренняя и вечерняя сводки по расписанию пар.
Однопользовательский — отвечает только `ALLOWED_USER_ID`, остальных молча игнорирует.

Стек: Python 3.11+, aiogram 3, notion-client 3 (Notion API `2025-09-03`, запросы к data source),
APScheduler 3, openai SDK (OpenRouter), pydantic, PyYAML.

## Что умеет

| Команда / кнопка | Что показывает |
|---|---|
| `/today` · 📅 Сегодня | пары, тройка дня, дедлайны сегодня |
| `/tomorrow` · 🌙 Завтра | то же на завтра |
| `/deadlines` · ⏰ Дедлайны | открытые задачи со сроком на 7 дней вперёд |
| `/overdue` · ❗ Просрочено | просроченные открытые задачи |
| `/cat` · 🗂 Категории | выбор категории → её открытые задачи |
| `/add название \| ДД.ММ [ЧЧ:ММ]` | добавить задачу без LLM |
| любой текст | LLM разбирает его в задачу → карточка «Сохранить / Изменить / Отмена» |

- Под каждым списком — кнопки `▶️ В работу` и `✅ Готово`: меняют Status в Notion и обновляют сообщение.
- Задачи `Done` и `Archived` нигде не показываются.
- **Тройка дня** — задачи с полем «Фокус на» = эта дата (выбираются вне бота). Если поля в базе нет, бот пишет предупреждение в лог и работает без этого блока.
- Категории и разделы бот берёт из схемы базы (обновляет раз в 10 минут), так что новые варианты, добавленные в Notion, подхватываются без правки кода.
- **Утренняя сводка** — за 2 ч до первой пары, за 30 мин если первая пара онлайн, в дни без пар — в 10:00.
  Содержит пары, тройку, дедлайны на сегодня + 3 дня, просроченное.
- **Вечерняя сводка** в 22:30 — пары и тройка на завтра, дедлайны завтра (или ближайшие, если тройка не выбрана).

## 1. Установка

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux
pip install -r requirements.txt
```

Скопируй `.env.example` в `.env` и заполни значения (см. ниже).
`.env` в `.gitignore` — в репозиторий он не попадает.

## 2. Получение токенов

### Telegram
1. Напиши [@BotFather](https://t.me/BotFather) → `/newbot` → получи токен → `BOT_TOKEN`.
2. Узнай свой числовой id у [@userinfobot](https://t.me/userinfobot) → `ALLOWED_USER_ID`.
   Если id не совпадает, бот молча игнорирует сообщения и пишет в лог `Игнорирую апдейт от чужого user_id=...` — оттуда тоже можно взять свой id.

### Notion
1. Открой <https://www.notion.so/profile/integrations> → **New integration** → тип **Internal**,
   выбери свой workspace. Возможности: *Read content*, *Update content*, *Insert content*.
2. Скопируй **Internal Integration Secret** → `NOTION_TOKEN`.
3. **Дай интеграции доступ к базе:** открой базу «Задачи и дедлайны» → `•••` (справа сверху) →
   **Connections** → **Add connections** → выбери свою интеграцию. Без этого API вернёт 404
   («Notion не видит базу»).
4. **ID data source** → `NOTION_DATA_SOURCE_ID`. Бот работает с Notion API `2025-09-03`, где
   запросы идут к data source, а не к базе. ID можно скопировать в настройках базы
   (`•••` → *Manage data sources* → *Copy data source ID*), либо получить из ID базы —
   это 32 символа в ссылке на базу `notion.so/<workspace>/<ID базы>?v=...`:

   ```bash
   python -c "from notion_client import Client; import sys; print([d['id'] for d in Client(auth=sys.argv[1]).databases.retrieve(database_id=sys.argv[2])['data_sources']])" <NOTION_TOKEN> <ID базы>
   ```

Ожидаемая схема базы: `Task name` (title), `Due` (date), `Status` (status: Not started / In progress /
Done / Archived), `Категория` (select), `Раздел` (select), `Заметки` (rich text),
`Фокус на` (date, необязательно — без него нет блока «тройка»).

### OpenRouter
1. Создай ключ на <https://openrouter.ai/keys> → `OPENROUTER_API_KEY`.
2. Выбери модель на <https://openrouter.ai/models> и впиши её слаг в `LLM_MODEL`
   (например, `deepseek/...:free`). Бесплатные модели бывают медленными (20–30 с на ответ).
   Без ключа/модели бот работает, но добавлять задачи можно только через `/add`.

## 3. Расписание пар

Пары и время сводок — в `schedule.yaml`. Скопируй пример и впиши свои пары
(формат описан в комментариях в начале файла):

```bash
cp schedule.example.yaml schedule.yaml
```

`schedule.yaml` в `.gitignore` — твоё расписание не попадает в репозиторий.
Чётность недель считается от `WEEK_A_MONDAY` в `.env` (понедельник недели А).
**После правки `schedule.yaml` перезапусти бота.** Если в файле ошибка, бот не запустится и напишет в лог, где она.

## 4. Запуск локально

```bash
python -m bot.main
```

В Telegram отправь боту `/start` — придёт справка и клавиатура.

> Один токен — один запущенный бот. Если бот уже крутится на сервере, локальный
> экземпляр получит `TelegramConflictError` (и наоборот) — останови один из них.

## 5. Тесты

```bash
python -m pytest -q
```

Тесты не ходят в сеть: чётность недель, время утренней сводки по дням, пары А/Б,
валидация ответа LLM, простой парсер `/add`, тройка дня и сводки, доступ только для
`ALLOWED_USER_ID`, работа без поля «Фокус на».

## 6. Деплой на VPS (systemd)

Нужен Linux с Python 3.11+ (Ubuntu 24.04 / Debian 12 подойдут). Часовой пояс сервера
не важен — бот всё считает в `Europe/Moscow`.

**1. Пользователь и код**

```bash
sudo apt update && sudo apt install -y python3 python3-venv git
sudo useradd --system --create-home --home-dir /opt/notion-bot --shell /usr/sbin/nologin notionbot
sudo -u notionbot git clone <URL-репозитория> /opt/notion-bot/app
# или скопируй папку проекта: scp -r ./tg_bot user@server:/tmp/ && sudo mv /tmp/tg_bot /opt/notion-bot/app
```

**2. Окружение и секреты**

```bash
cd /opt/notion-bot/app
sudo -u notionbot python3 -m venv .venv
sudo -u notionbot .venv/bin/pip install -r requirements.txt
sudo -u notionbot cp .env.example .env
sudo -u notionbot nano .env          # вставь токены
sudo chmod 600 .env
# schedule.yaml не в git — скопируй свой с компьютера:
#   scp schedule.yaml user@server:/tmp/ && sudo -u notionbot cp /tmp/schedule.yaml /opt/notion-bot/app/
sudo -u notionbot .venv/bin/python -m pytest -q   # проверка
```

**3. Сервис** — `/etc/systemd/system/notion-bot.service`:

```ini
[Unit]
Description=Notion tasks Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=notionbot
Group=notionbot
WorkingDirectory=/opt/notion-bot/app
ExecStart=/opt/notion-bot/app/.venv/bin/python -m bot.main
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

# Ограничения: боту не нужно писать на диск
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now notion-bot
systemctl status notion-bot
journalctl -u notion-bot -f          # логи в реальном времени
```

В логе должно быть `Бот @... запущен` и строки `Задача evening: следующий запуск ...`.

**Обновление**

```bash
cd /opt/notion-bot/app
sudo -u notionbot git pull
sudo -u notionbot .venv/bin/pip install -r requirements.txt
sudo systemctl restart notion-bot
```

После правки `schedule.yaml` или `.env` на сервере — тоже `sudo systemctl restart notion-bot`.

**Если бот упал** — `Restart=always` поднимет его через 10 с; если была пропущена сводка,
она отправится, если бот поднялся в течение 15 минут после её времени.
