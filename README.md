# 🚀 Yandex Cloud Function Project

Шаблон для развертывания приложений в Yandex Cloud Functions через SourceCraft.

## 📁 Структура проекта

```
project/
├── src/                    # Исходный код приложения
│   ├── index.js           # Основной файл функции
│   ├── package.json       # Зависимости Node.js
│   └── .env.example       # Пример переменных окружения
├── .sourcecraft/          # Конфигурация CI/CD
│   └── ci.yaml           # Конфигурация workflow
├── .gitignore            # Игнорируемые файлы
└── README.md             # Эта документация
```

## 🔧 Настройка переменных окружения

### 1. Создайте файл `.env` в папке `src/`:

```bash
# Пример .env файла
BOT_TOKEN=your_telegram_bot_token_here
API_KEY=your_api_key_here
DATABASE_URL=your_database_url_here
ADMIN_ID=your_telegram_id_here
```

### 2. Использование в коде:

```javascript
// index.js
require('dotenv').config();

const BOT_TOKEN = process.env.BOT_TOKEN;
const API_KEY = process.env.API_KEY;

if (!BOT_TOKEN) {
  console.error('❌ ОШИБКА: BOT_TOKEN не установлен!');
  process.exit(1);
}
```

## 🚀 Развертывание в Yandex Cloud

### Через SourceCraft CI/CD:

1. **Настройте сервисное подключение** в SourceCraft
2. **Запустите workflow** `deploy-function-workflow`
3. **Укажите переменные окружения** в форме запуска

### Переменные окружения в Yandex Cloud:

В Yandex Cloud Functions переменные окружения настраиваются:
- Через интерфейс Yandex Cloud Console
- Через параметр `ENVIRONMENT` в CI/CD конфигурации
- Через yc CLI: `yc serverless function set-environment`

## 📦 CI/CD Конфигурация

Пример `.sourcecraft/ci.yaml`:

```yaml
workflows:
  deploy-function-workflow:
    inputs:
      function-name:
        type: string
        required: true
      environment-vars:
        type: string
        default: ""
        description: "Переменные окружения в формате KEY1=value1,KEY2=value2"
    
    env:
      YC_FUNCTION_NAME: ${{ inputs.function-name }}
      ENVIRONMENT: ${{ inputs.environment-vars }}
    
    tasks:
      - name: deploy
        cubes:
          - name: deploy-function
            env:
              YC_FUNCTION_RUNTIME: nodejs22
              YC_FUNCTION_ENTRYPOINT: index.handler
              SOURCE_PATH: "./src"
              PUBLIC: true
            image: cr.yandex/sourcecraft/yc-function:latest
```

## 🔒 Безопасность

### Что НЕ коммитить в Git:
- ✅ `.env` файлы
- ✅ Ключи API
- ✅ Токены доступа
- ✅ Пароли
- ✅ Приватные ключи

### Что коммитить:
- ✅ `.env.example` (без реальных значений)
- ✅ Код приложения
- ✅ Конфигурационные файлы
- ✅ Документацию

## 💻 Локальная разработка

### 1. Клонируйте репозиторий:

```bash
git clone https://sourcecraft.dev/ilyanull4/agent-bot
cd agent-bot
```

### 2. Установите зависимости:

```bash
cd src
npm install
```

### 3. Настройте окружение:

```bash
cp .env.example .env
# Отредактируйте .env файл
```

### 4. Запустите локально:

```bash
node index.js
```

## 🌐 Деплой через Git

### 1. Инициализируйте Git:

```bash
git init
git add .
git commit -m "Initial commit"
```

### 2. Добавьте удаленный репозиторий:

```bash
git remote add origin https://sourcecraft.dev/ilyanull4/agent-bot
```

### 3. Закоммитьте изменения:

```bash
git add .
git commit -m "Your commit message"
git push origin main
```

### 4. Запустите деплой в SourceCraft:

- Перейдите в CI/CD репозитория
- Запустите workflow с нужными параметрами

## 🛠️ Полезные команды

### Проверка функции:

```bash
# Проверить статус функции
curl https://functions.yandexcloud.net/your-function-id

# Тестирование с данными
curl -X POST https://functions.yandexcloud.net/your-function-id \
  -H "Content-Type: application/json" \
  -d '{"test": "data"}'
```

### Управление через yc CLI:

```bash
# Установить переменные окружения
yc serverless function set-environment \
  --id your-function-id \
  --environment "KEY1=value1,KEY2=value2"

# Получить логи
yc serverless function logs --id your-function-id
```

## 📞 Поддержка

- [Документация Yandex Cloud Functions](https://cloud.yandex.ru/docs/functions/)
- [Документация SourceCraft](https://sourcecraft.dev/portal/docs)
- [Node.js документация](https://nodejs.org/docs/)

## 📄 Лицензия

MIT License