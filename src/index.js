const { Telegraf, Markup } = require('telegraf');
const axios = require('axios');
require('dotenv').config();

// Конфигурация
const ADMINS = process.env.ADMINS ? process.env.ADMINS.split(',').map(id => parseInt(id.trim())).filter(id => !isNaN(id)) : [];
const YANDEX_WEATHER_API_KEY = process.env.YANDEX_WEATHER_API_KEY || '';

// Хранилище для сообщений пользователей (в реальном приложении используйте БД)
const userMessages = new Map(); // chatId -> { messages: [], username, firstName, lastName }
const adminReplies = new Map(); // messageId -> { userId, originalMessage }

const bot = new Telegraf(process.env.BOT_TOKEN);

// ==================== УТИЛИТЫ ====================

// Проверка, является ли пользователь админом
function isAdmin(userId) {
  return ADMINS.includes(userId);
}

// Получить информацию о пользователе
function getUserInfo(ctx) {
  const user = ctx.message.from;
  return {
    id: user.id,
    username: user.username || `user_${user.id}`,
    firstName: user.first_name || '',
    lastName: user.last_name || '',
    fullName: `${user.first_name || ''} ${user.last_name || ''}`.trim() || `Пользователь ${user.id}`
  };
}

// Форматирование сообщения для админа
function formatMessageForAdmin(userInfo, messageText, chatId) {
  return `📨 *НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ*\n\n` +
         `👤 *Пользователь:* ${userInfo.fullName}\n` +
         `🔖 *Username:* @${userInfo.username}\n` +
         `🆔 *ID:* ${userInfo.id}\n` +
         `💬 *Сообщение:* ${messageText}\n\n` +
         `📎 *Chat ID:* ${chatId}`;
}

// Форматирование ответа админа для пользователя
function formatReplyForUser(adminMessage) {
  return `📩 *ОТВЕТ ОТ АДМИНИСТРАТОРА:*\n\n${adminMessage}`;
}

// Отправить уведомление всем админам
async function notifyAdmins(message, options = {}) {
  const promises = ADMINS.map(adminId => {
    return bot.telegram.sendMessage(adminId, message, options).catch(err => {
      console.error(`Ошибка отправки уведомления админу ${adminId}:`, err.message);
      return null;
    });
  });
  
  return Promise.all(promises);
}

// ==================== КОМАНДА ПОГОДЫ ====================

// Получить погоду через Яндекс API
async function getWeather(city = 'Москва') {
  try {
    if (!YANDEX_WEATHER_API_KEY) {
      throw new Error('API ключ Яндекс Погоды не настроен');
    }

    // Геокодирование города (получаем координаты)
    const geocodeResponse = await axios.get(
      `https://geocode-maps.yandex.ru/1.x/`,
      {
        params: {
          apikey: YANDEX_WEATHER_API_KEY,
          geocode: city,
          format: 'json',
          results: 1
        }
      }
    );

    const featureMember = geocodeResponse.data.response.GeoObjectCollection.featureMember;
    if (!featureMember || featureMember.length === 0) {
      throw new Error('Город не найден');
    }

    const pos = featureMember[0].GeoObject.Point.pos.split(' ');
    const [lon, lat] = pos.map(Number);

    // Получаем погоду
    const weatherResponse = await axios.get(
      `https://api.weather.yandex.ru/v2/forecast`,
      {
        params: {
          lat: lat,
          lon: lon,
          lang: 'ru_RU',
          limit: 1,
          hours: false,
          extra: false
        },
        headers: {
          'X-Yandex-API-Key': YANDEX_WEATHER_API_KEY
        }
      }
    );

    const fact = weatherResponse.data.fact;
    const forecast = weatherResponse.data.forecast;

    // Форматируем ответ
    const weatherConditions = {
      'clear': '☀️ Ясно',
      'partly-cloudy': '⛅️ Малооблачно',
      'cloudy': '☁️ Облачно с прояснениями',
      'overcast': '🌫️ Пасмурно',
      'drizzle': '🌦️ Морось',
      'light-rain': '🌦️ Небольшой дождь',
      'rain': '🌧️ Дождь',
      'moderate-rain': '🌧️ Умеренно сильный дождь',
      'heavy-rain': '⛈️ Сильный дождь',
      'continuous-heavy-rain': '⛈️ Длительный сильный дождь',
      'showers': '🌧️ Ливень',
      'wet-snow': '🌨️ Дождь со снегом',
      'light-snow': '🌨️ Небольшой снег',
      'snow': '❄️ Снег',
      'snow-showers': '❄️ Снегопад',
      'hail': '🌨️ Град',
      'thunderstorm': '⛈️ Гроза',
      'thunderstorm-with-rain': '⛈️ Гроза с дождем',
      'thunderstorm-with-hail': '⛈️ Гроза с градом'
    };

    const condition = weatherConditions[fact.condition] || fact.condition;
    
    return `🌤️ *Погода в ${city}:*\n\n` +
           `${condition}\n` +
           `🌡️ Температура: ${fact.temp}°C (ощущается как ${fact.feels_like}°C)\n` +
           `💨 Ветер: ${fact.wind_speed} м/с, ${fact.wind_dir}\n` +
           `💧 Влажность: ${fact.humidity}%\n` +
           `📊 Давление: ${fact.pressure_mm} мм рт. ст.\n\n` +
           `📅 *Прогноз на сегодня:*\n` +
           `🌅 Утро: ${forecast.parts.morning.temp_avg}°C\n` +
           `☀️ День: ${forecast.parts.day.temp_avg}°C\n` +
           `🌇 Вечер: ${forecast.parts.evening.temp_avg}°C\n` +
           `🌙 Ночь: ${forecast.parts.night.temp_avg}°C`;

  } catch (error) {
    console.error('Ошибка получения погоды:', error.message);
    
    if (error.response?.status === 403) {
      return '❌ *Ошибка:* Неверный или отсутствующий API ключ Яндекс Погоды.\n\n' +
             'Для использования функции погоды:\n' +
             '1. Получите API ключ на https://developer.tech.yandex.ru/services/\n' +
             '2. Добавьте его в переменные окружения как YANDEX_WEATHER_API_KEY';
    }
    
    if (error.message.includes('Город не найден')) {
      return '❌ *Город не найден.* Пожалуйста, укажите корректное название города.';
    }
    
    return '❌ *Не удалось получить данные о погоде.* Пожалуйста, попробуйте позже.';
  }
}

// ==================== ОСНОВНЫЕ КОМАНДЫ ====================

// Команда /start
bot.start((ctx) => {
  const userInfo = getUserInfo(ctx);
  
  const welcomeMessage = `👋 *Привет, ${userInfo.firstName || 'друг'}!*\n\n` +
    `Я — ваш персональный бот-агент! 🤖\n\n` +
    `*Что я умею:*\n` +
    `📨 *Принимать ваши сообщения* и уведомлять администратора\n` +
    `⛅ *Показывать погоду* в любом городе (/weather Москва)\n` +
    `👤 *Связывать вас с админом* для личного общения\n\n` +
    `*Доступные команды:*\n` +
    `/start - Начало работы\n` +
    `/help - Помощь и список команд\n` +
    `/weather [город] - Погода в указанном городе\n` +
    `/status - Статус ваших сообщений\n\n` +
    `Просто напишите мне сообщение, и админ скоро с вами свяжется!`;
  
  ctx.reply(welcomeMessage, { parse_mode: 'Markdown' });
  
  // Уведомляем админов о новом пользователе
  if (ADMINS.length > 0) {
    notifyAdmins(
      `🆕 *НОВЫЙ ПОЛЬЗОВАТЕЛЬ ЗАПУСТИЛ БОТА*\n\n` +
      `👤 ${userInfo.fullName}\n` +
      `🔖 @${userInfo.username}\n` +
      `🆔 ${userInfo.id}`,
      { parse_mode: 'Markdown' }
    );
  }
});

// Команда /help
bot.help((ctx) => {
  const helpMessage = `🆘 *Помощь по боту-агенту*\n\n` +
    `*Основные команды:*\n` +
    `/start - Начало работы с ботом\n` +
    `/help - Это сообщение помощи\n` +
    `/weather [город] - Погода в указанном городе\n` +
    `/status - Статус ваших сообщений\n\n` +
    `*Как это работает:*\n` +
    `1. Вы пишете мне сообщение\n` +
    `2. Я уведомляю администратора\n` +
    `3. Админ отвечает вам в личном чате\n` +
    `4. Вы получаете ответ через меня\n\n` +
    `*Примеры:*\n` +
    `• "Привет, хочу задать вопрос"\n` +
    `• "/weather Санкт-Петербург"\n` +
    `• "Как с вами связаться?"`;
  
  ctx.reply(helpMessage, { parse_mode: 'Markdown' });
});

// Команда /weather
bot.command('weather', async (ctx) => {
  const args = ctx.message.text.split(' ').slice(1);
  const city = args.join(' ') || 'Москва';
  
  // Показываем "типинг" для лучшего UX
  ctx.replyWithChatAction('typing');
  
  const weatherMessage = await getWeather(city);
  ctx.reply(weatherMessage, { parse_mode: 'Markdown' });
});

// Команда /status
bot.command('status', (ctx) => {
  const userInfo = getUserInfo(ctx);
  const userData = userMessages.get(userInfo.id);
  
  if (!userData || userData.messages.length === 0) {
    ctx.reply(
      '📭 *У вас пока нет отправленных сообщений.*\n\n' +
      'Напишите мне что-нибудь, и админ скоро с вами свяжется!',
      { parse_mode: 'Markdown' }
    );
    return;
  }
  
  const lastMessage = userData.messages[userData.messages.length - 1];
  const statusMessage = `📊 *СТАТУС ВАШИХ СООБЩЕНИЙ*\n\n` +
    `📨 Всего сообщений: ${userData.messages.length}\n` +
    `⏰ Последнее сообщение: ${lastMessage.timestamp}\n` +
    `💬 Текст: "${lastMessage.text.substring(0, 50)}${lastMessage.text.length > 50 ? '...' : ''}"\n\n` +
    `Админ уведомлен о ваших сообщениях и ответит в ближайшее время!`;
  
  ctx.reply(statusMessage, { parse_mode: 'Markdown' });
});

// ==================== ОБРАБОТКА СООБЩЕНИЙ ====================

// Обработка текстовых сообщений от пользователей
bot.on('text', async (ctx) => {
  const userInfo = getUserInfo(ctx);
  const messageText = ctx.message.text;
  const chatId = ctx.message.chat.id;
  const messageId = ctx.message.message_id;
  
  // Игнорируем команды (они уже обработаны)
  if (messageText.startsWith('/')) {
    return;
  }
  
  // Сохраняем сообщение пользователя
  if (!userMessages.has(userInfo.id)) {
    userMessages.set(userInfo.id, {
      username: userInfo.username,
      firstName: userInfo.firstName,
      lastName: userInfo.lastName,
      messages: []
    });
  }
  
  const timestamp = new Date().toLocaleString('ru-RU');
  userMessages.get(userInfo.id).messages.push({
    text: messageText,
    timestamp: timestamp,
    messageId: messageId
  });
  
  // Подтверждаем получение сообщения
  const confirmationMessage = await ctx.reply(
    `✅ *Сообщение получено!*\n\n` +
    `Ваше сообщение: "${messageText.substring(0, 100)}${messageText.length > 100 ? '...' : ''}"\n\n` +
    `Админ уведомлен и ответит вам в ближайшее время.`,
    { parse_mode: 'Markdown' }
  );
  
  // Уведомляем админов
  if (ADMINS.length > 0) {
    try {
      const adminMessage = formatMessageForAdmin(userInfo, messageText, chatId);
      
      const adminReplies = await notifyAdmins(
        adminMessage,
        {
          parse_mode: 'Markdown',
          reply_markup: Markup.inlineKeyboard([
            [
              Markup.button.callback(
                '📨 Ответить пользователю',
                `reply_${userInfo.id}_${messageId}`
              )
            ],
            [
              Markup.button.callback(
                '👤 Профиль пользователя',
                `profile_${userInfo.id}`
              )
            ]
          ]).reply_markup
        }
      );
      
      // Сохраняем связь между сообщением админа и пользователем
      adminReplies.forEach((adminReply, index) => {
        if (adminReply) {
          adminRepliesMap.set(adminReply.message_id, {
            userId: userInfo.id,
            originalMessage: messageText,
            userMessageId: messageId,
            userChatId: chatId,
            adminId: ADMINS[index]
          });
        }
      });
      
    } catch (error) {
      console.error('Ошибка отправки уведомления админам:', error);
      ctx.reply('⚠️ *Внимание:* Админы временно недоступны. Ваше сообщение сохранено.');
    }
  } else {
    console.warn('ADMINS не настроены. Уведомления не отправляются.');
    ctx.reply('ℹ️ *Информация:* Админские уведомления не настроены. Ваше сообщение сохранено.');
  }
});

// ==================== ИНЛАЙН КНОПКИ ДЛЯ АДМИНОВ ====================

// Обработка callback-кнопок
bot.action(/reply_(.+)_(.+)/, async (ctx) => {
  const [_, userId, messageId] = ctx.match;
  const userData = userMessages.get(parseInt(userId));
  
  if (!userData) {
    ctx.answerCbQuery('Пользователь не найден');
    return;
  }
  
  // Проверяем, является ли пользователь админом
  if (!isAdmin(ctx.from.id)) {
    ctx.answerCbQuery('Только админы могут отвечать');
    return;
  }
  
  // Сохраняем состояние для ответа
  ctx.session = ctx.session || {};
  ctx.session.replyTo = {
    userId: parseInt(userId),
    messageId: parseInt(messageId),
    username: userData.username,
    adminId: ctx.from.id
  };
  
  ctx.answerCbQuery();
  
  // Запрашиваем текст ответа
  ctx.reply(
    `✍️ *ОТВЕТ ПОЛЬЗОВАТЕЛЮ @${userData.username}*\n\n` +
    `Введите текст ответа:`,
    { parse_mode: 'Markdown' }
  );
});

// Просмотр профиля пользователя
bot.action(/profile_(.+)/, async (ctx) => {
  const userId = parseInt(ctx.match[1]);
  const userData = userMessages.get(userId);
  
  if (!userData) {
    ctx.answerCbQuery('Пользователь не найден');
    return;
  }
  
  // Проверяем, является ли пользователь админом
  if (!isAdmin(ctx.from.id)) {
    ctx.answerCbQuery('Только админы могут просматривать профили');
    return;
  }
  
  const profileMessage = `👤 *ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ*\n\n` +
    `🔖 Username: @${userData.username}\n` +
    `👤 Имя: ${userData.firstName} ${userData.lastName}\n` +
    `🆔 ID: ${userId}\n` +
    `📨 Всего сообщений: ${userData.messages.length}\n\n` +
    `*Последние сообщения:*\n` +
    userData.messages.slice(-3).map((msg, i) => 
      `${i + 1}. ${msg.timestamp}: "${msg.text.substring(0, 50)}${msg.text.length > 50 ? '...' : ''}"`
    ).join('\n');
  
  ctx.answerCbQuery();
  ctx.reply(profileMessage, { parse_mode: 'Markdown' });
});

// ==================== ОБРАБОТКА ОТВЕТОВ АДМИНОВ ====================

// Обработка ответов админов (только если сообщение от админа)
bot.on('text', async (ctx) => {
  // Проверяем, что сообщение от админа и есть состояние для ответа
  if (isAdmin(ctx.message.from.id) && ctx.session?.replyTo) {
    const replyData = ctx.session.replyTo;
    const replyText = ctx.message.text;
    
    // Проверяем, что админ отвечает на свой же запрос
    if (replyData.adminId !== ctx.message.from.id) {
      ctx.reply('❌ *Ошибка:* Вы можете отвечать только на свои запросы.');
      delete ctx.session.replyTo;
      return;
    }
    
    try {
      // Отправляем ответ пользователю
      await bot.telegram.sendMessage(
        replyData.userId,
        formatReplyForUser(replyText),
        { parse_mode: 'Markdown' }
      );
      
      // Подтверждаем админу
      ctx.reply(
        `✅ *Ответ отправлен пользователю @${replyData.username}*\n\n` +
        `Текст ответа: "${replyText.substring(0, 100)}${replyText.length > 100 ? '...' : ''}"`,
        { parse_mode: 'Markdown' }
      );
      
      // Очищаем состояние
      delete ctx.session.replyTo;
      
    } catch (error) {
      console.error('Ошибка отправки ответа пользователю:', error);
      ctx.reply(
        `❌ *Не удалось отправить ответ пользователю.*\n\n` +
        `Возможно, пользователь заблокировал бота.`,
        { parse_mode: 'Markdown' }
      );
    }
  }
});

// ==================== АДМИНСКИЕ КОМАНДЫ ====================

// Команда /admin для админов
bot.command('admin', (ctx) => {
  if (!isAdmin(ctx.message.from.id)) {
    ctx.reply('❌ *Доступ запрещен.* Эта команда только для админов.');
    return;
  }
  
  const adminMessage = `👑 *ПАНЕЛЬ АДМИНИСТРАТОРА*\n\n` +
    `*Статистика:*\n` +
    `👥 Всего пользователей: ${userMessages.size}\n` +
    `📨 Всего сообщений: ${Array.from(userMessages.values()).reduce((sum, user) => sum + user.messages.length, 0)}\n\n` +
    `*Команды:*\n` +
    `/admin - Эта панель\n` +
    `/users - Список пользователей\n` +
    `/broadcast [сообщение] - Рассылка всем пользователям\n\n` +
    `*Информация:*\n` +
    `Ваш ID: ${ctx.message.from.id}\n` +
    `Всего админов: ${ADMINS.length}`;
  
  ctx.reply(adminMessage, { parse_mode: 'Markdown' });
});

// Команда /users для админов
bot.command('users', (ctx) => {
  if (!isAdmin(ctx.message.from.id)) {
    ctx.reply('❌ *Доступ запрещен.* Эта команда только для админов.');
    return;
  }
  
  if (userMessages.size === 0) {
    ctx.reply('📭 *Пользователей пока нет.*');
    return;
  }
  
  let usersList = `👥 *СПИСОК ПОЛЬЗОВАТЕЛЕЙ (${userMessages.size}):*\n\n`;
  
  Array.from(userMessages.entries()).slice(0, 20).forEach(([userId, userData], index) => {
    usersList += `${index + 1}. @${userData.username} (ID: ${userId})\n`;
    usersList += `   Сообщений: ${userData.messages.length}\n`;
    if (userData.messages.length > 0) {
      const lastMsg = userData.messages[userData.messages.length - 1];
      usersList += `   Последнее: "${lastMsg.text.substring(0, 30)}${lastMsg.text.length > 30 ? '...' : ''}"\n`;
    }
    usersList += '\n';
  });
  
  if (userMessages.size > 20) {
    usersList += `... и еще ${userMessages.size - 20} пользователей`;
  }
  
  ctx.reply(usersList, { parse_mode: 'Markdown' });
});

// ==================== ОБРАБОТЧИК ДЛЯ YANDEX CLOUD FUNCTIONS ====================

module.exports.handler = async function (event, context) {
  try {
    const message = JSON.parse(event.body);
    await bot.handleUpdate(message);
    
    return {
      statusCode: 200,
      body: JSON.stringify({ ok: true }),
      headers: {
        'Content-Type': 'application/json'
      }
    };
    
  } catch (error) {
    console.error('Ошибка обработки запроса:', error);
    
    return {
      statusCode: 500,
      body: JSON.stringify({ 
        ok: false, 
        error: error.message 
      }),
      headers: {
        'Content-Type': 'application/json'
      }
    };
  }
};

// ==================== ИНФОРМАЦИЯ О БОТЕ ====================

console.log('🤖 Telegram Agent Bot запущен!');
console.log('📝 Функции:');
console.log('  • Уведомления админов о новых сообщениях');
console.log('  • Погода через Яндекс API');
console.log('  • Перенаправление сообщений');
console.log('  • Ответы админов пользователям');
console.log('  • Админская панель (/admin)');

if (ADMINS.length === 0) {
  console.warn('⚠️  ADMINS не настроены. Уведомления админов не будут работать.');
  console.log('   Для настройки добавьте переменную окружения ADMINS с Telegram ID админов (через запятую)');
} else {
  console.log(`✅ Настроено админов: ${ADMINS.length}`);
}

if (!YANDEX_WEATHER_API_KEY) {
  console.warn('⚠️  YANDEX_WEATHER_API_KEY не настроен. Функция погоды будет ограничена.');
  console.log('   Для настройки добавьте переменную окружения YANDEX_WEATHER_API_KEY');
} else {
  console.log('✅ Яндекс Погода API настроен');
}