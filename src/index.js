// Пример Yandex Cloud Function с использованием переменных окружения
require('dotenv').config();

// Загрузка переменных окружения
const API_KEY = process.env.API_KEY;
const SECRET_TOKEN = process.env.SECRET_TOKEN;
const DEBUG_MODE = process.env.DEBUG_MODE === 'true';
const ADMIN_ID = process.env.ADMIN_ID ? parseInt(process.env.ADMIN_ID) : null;

// Проверка обязательных переменных
const requiredEnvVars = ['API_KEY'];
requiredEnvVars.forEach(varName => {
  if (!process.env[varName]) {
    console.error(`❌ ОШИБКА: Переменная окружения ${varName} не установлена!`);
    console.error(`   Добавьте ${varName} в переменные окружения Yandex Cloud`);
    process.exit(1);
  }
});

// Основной обработчик функции
module.exports.handler = async function (event, context) {
  try {
    // Логирование для отладки
    if (DEBUG_MODE) {
      console.log('🔧 Режим отладки включен');
      console.log('📦 Получен event:', JSON.stringify(event, null, 2));
      console.log('🔑 API_KEY установлен:', !!API_KEY);
      console.log('👑 ADMIN_ID:', ADMIN_ID);
    }

    // Парсинг входящих данных
    let data;
    try {
      data = typeof event.body === 'string' ? JSON.parse(event.body) : event.body;
    } catch (e) {
      data = event.body || event;
    }

    // Пример обработки запроса
    const response = {
      status: 'success',
      timestamp: new Date().toISOString(),
      message: 'Функция успешно выполнена!',
      environment: {
        debugMode: DEBUG_MODE,
        hasApiKey: !!API_KEY,
        hasSecretToken: !!SECRET_TOKEN,
        adminId: ADMIN_ID
      },
      receivedData: data,
      metadata: {
        functionName: context.functionName,
        requestId: context.requestId,
        memoryLimit: context.memoryLimitInMB
      }
    };

    // Возврат успешного ответа
    return {
      statusCode: 200,
      body: JSON.stringify(response, null, 2),
      headers: {
        'Content-Type': 'application/json',
        'X-Powered-By': 'Yandex Cloud Functions'
      }
    };

  } catch (error) {
    console.error('❌ Ошибка выполнения функции:', error);
    
    // Возврат ошибки
    return {
      statusCode: 500,
      body: JSON.stringify({
        status: 'error',
        timestamp: new Date().toISOString(),
        error: error.message,
        stack: DEBUG_MODE ? error.stack : undefined
      }, null, 2),
      headers: {
        'Content-Type': 'application/json'
      }
    };
  }
};

// Дополнительные функции (опционально)
function validateApiKey(apiKey) {
  return apiKey === API_KEY;
}

function isAdmin(userId) {
  return ADMIN_ID && userId === ADMIN_ID;
}

function logRequest(data) {
  if (DEBUG_MODE) {
    console.log('📨 Запрос:', data);
  }
}

// Экспорт вспомогательных функций
module.exports = {
  ...module.exports,
  validateApiKey,
  isAdmin,
  logRequest
};

// Информация при запуске
console.log('🚀 Функция инициализирована');
console.log('📋 Переменные окружения:');
console.log(`   • DEBUG_MODE: ${DEBUG_MODE}`);
console.log(`   • API_KEY: ${API_KEY ? 'установлен' : 'НЕ УСТАНОВЛЕН!'}`);
console.log(`   • SECRET_TOKEN: ${SECRET_TOKEN ? 'установлен' : 'не установлен'}`);
console.log(`   • ADMIN_ID: ${ADMIN_ID || 'не установлен'}`);

if (!API_KEY) {
  console.error('⚠️  ВНИМАНИЕ: API_KEY не установлен!');
  console.error('   Установите переменную окружения API_KEY в Yandex Cloud');
}