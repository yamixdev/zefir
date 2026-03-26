# Инструкция по развертыванию

### Настройте  интеграцию с Yandex Cloud

В настройках вашей организации SourceCraft создайте сервисное подключение (Settings-\>Service Connections). Для развертывания Telegram-бота подойдут настройки по умолчанию.

{% note info "SourceCraft грант на сервисы облака Yandex Cloud" %}

Если вы находитесь в персональной организации SourceCraft  вам будет предложено активировать грант на сервисы облака.

Персональная организация создается автоматически при регистрации в SourceCraft и заканчивается на Personal Organization (SourceСraft), в описании указано Created By SourceCraft.

{% endnote %}

### Зарегистрируйте Telegram-бота {#3-telegram-}

Зарегистрируйте вашего бота в Telegram и получите токен.

1. Для регистрации нового бота запустите бота [BotFather](https://t.me/BotFather) и отправьте команду:

   ```
   /newbot
   ```

2. Задайте имя (name) и имя пользователя (username) для бота. Имя пользователя должно оканчиваться на `...Bot` или `..._bot`.

   Например:

   * name: demo-bot

   * username: demobot

   В результате вы получите токен. Сохраните его, он потребуется на следующих шагах.

### Запустите процесс сборки и развертывания вашего бота

Перейдите в секцию CI/CD для вашего репозитория и запустите CI/CD процесс (кнопка New Launch), где в качестве параметра bot-token укажите  токен, который вы получили на предыдущем шаге от BotFather. bot-token необходим для успешной связки вашей cloud function с ботом.

После успешного завершения CI/CD процесса необходимо убедиться что ваша cloud function доступна публично без аутентификации. Для автоматической публикации без аутентификации необходима роль function.admin или выше.

Местоположение, куда был развернута cloud function, можно увидеть кликнув по кубику get-outputs. Необходимо перейти по ссылке вида [https://console.yandex.cloud/folders/\<your\_folder\_id\>/functions/functions/\<your\_function\_id/overview](https://console.yandex.cloud/folders/%5C*%5C*%5C*/functions/functions/d4ei109bh4c15agt8k5t/overview) и включить опцию "Публичная функция" для работы с Telegram.

### **FAQ**

1. Возможно ли не передавать bot-token.

   Параметр bot-token является опциональным. Он необходим для автоматической привязки вашей cloud function к тг-боту. Если вы не передадите bot-token при первом запуске, то для регистрации бота вам необходимо выполнить привязку вашего публичного ендпоинта к тг-боту самостоятельно.

2. Функция развернулась, но бот не работает.

   Проверьте, что функция доступна по публичному адресу.

3. В логах кубика Permission Denied.

   Это сообщение выводится если не хватает прав у сервисного аккаунта. Для публикации функциии необходима [роль](https://yandex.cloud/ru/docs/functions/security/#functions-admin) `functions.admin`. Также вы можете опубликовать функцию в интерфейсе Yandex Cloud

4. Какие значения можно передавать в кубик с образом **cr.yandex/sourcecraft/yc-function**

   * Обязательные параметры

     **YC\_FUNCTION\_NAME** - имя функции, /\|\[a-z\]\[-a-z0-9\]\{1,61\}\[a-z0-9\]/, уникальное имя в каталоге, если функция с таким именем существует, при запуске ci/cd процесса произойдет создание новой версии.

     **YC\_FUNCTION\_RUNTIME** - идентификатор [среды выполнения](https://yandex.cloud/ru/docs/functions/concepts/runtime/#runtimes)

     **YC\_FUNCTION\_ENTRYPOINT** - точка входа, для каждой среды выполнения она задается согласно [документации](https://yandex.cloud/ru/docs/functions/quickstart/create-function/)

   * Другие параметры:

     **SOURCE\_PATH** - папка в репозитории откуда скопируются все файлы при развертывании новой версии функции

     **ENVIRONMENT** - аналог yc cli параметра --environment

     **PUBLIC** - делает функцию доступной публично, аналог yc cli параметра [allow-unauthenticated-invoke](https://yandex.cloud/ru/docs/cli/cli-ref/serverless/cli-ref/function/allow-unauthenticated-invoke), необходима роль functions.admin и выше для сервисного аккаунта.

     Другие примеры использования кубика [https://sourcecraft.dev/yandex-cloud-examples/serverless-functions](https://sourcecraft.dev/yandex-cloud-examples/serverless-functions/)

5. Не хватает нужных параметров для развертывания функции через кубик с образом **cr.yandex/sourcecraft/yc-function**

   Кубик **yc-function** подходит для базовых сценариев развертывания и не покрывает каждый параметр настройки cloud function. Для более сложных сценариев развертывания рекомендуем воспользоваться кубиком **cr.yandex/sourcecraft/yc-cli** в котором вы можете использовать все возможности yc cli.

   Пример:

   ```
   # Кубик с предустановленным Yandex Cloud CLI забирает из outputs 
   # переменную IAM_TOKEN и использует ее для получения списка функций Cloud Functions.
   - name: get-functions
     env:
       # Подставьте в блок для получения значений outputs имя кубика с
       # IAM-токеном, например get-iam-token.
       YC_IAM_TOKEN: ${{ cubes.<имя_кубика_с_IAM-токеном>.outputs.IAM_TOKEN }}
       YC_FOLDER_ID: ${{ tokens.<имя_токена>.folder_id }}
     image: 
       name: cr.yandex/sourcecraft/yc-cli:latest
       entrypoint: ""
     script:
       - |
         yc config set folder-id $YC_FOLDER_ID
         yc serverless function list
   ```

6. Я опытный пользователь GitHub могу ли я переиспользовать свои GitHub Actions в SourceCraft CI/CD

   Да, SourceCraft поддерживает запуск GitHub Actions. Также вы можете комбинировать несколько подходов в одном workflow, см. пример <https://sourcecraft.dev/sourcecraft/yc-ci-cd-serverless/browse/.sourcecraft/ci.yaml>