const { Telegraf } = require('telegraf');

// Глобальная переменная для хранения контекста
let globalContext = null;

const bot = new Telegraf(process.env.BOT_TOKEN);

bot.start((ctx) => ctx.reply(`Hello. \nMy name is Workflow Telegram Bot \nDeloyed by SourceCraft CI and Powered by Yandex Cloud Function.`))

bot.help((ctx) => ctx.reply(`Hello, ${ctx.message.from.username}.\nI can say Hello and start Yandex Cloud workflow if you specify workflowId`))

bot.on('text', async (ctx) => {

    const text = ctx.message.text;
    const chatId = ctx.message.chat.id;

    await ctx.reply(`Hello, ${ctx.message.from.username}`);

    //TODO edit workflowId for real workload
    var workflowId = null
    if (workflowId != null) {
        await startWorkflow(ctx, text, chatId, workflowId);
    }

});

async function startWorkflow(ctx, text, chatId, id) {
    // Вызываем Yandex Cloud Workflows
    try {
        // Получаем токен из глобального контекста
        const token = globalContext.token.access_token;
        
        if (!token) {
            await ctx.reply("Ошибка: отсутствует токен авторизации для вызова Yandex Cloud Workflows.");
            return;
        }
        
        const response = await fetch("https://serverless-workflows.api.cloud.yandex.net/workflows/v1/execution/start", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
                workflowId: id,
                input: {
                    inputJson: JSON.stringify({
                        message: text,
                        chatId: chatId
                    })
                }
            })
        });
        
        if (response.ok) {
            await ctx.reply("Сообщение успешно отправлено в Yandex Cloud Workflows.");
        } else {
            const errorText = await response.text();
            await ctx.reply(`Ошибка при отправке в Yandex Cloud Workflows. Статус: ${response.status}, Ответ: ${errorText}`);
        }
    } catch (error) {
        console.error("Ошибка при вызове Yandex Cloud Workflows:", error);
        await ctx.reply(`Произошла ошибка при отправке в Yandex Cloud Workflows: ${error.message}`);
    }
}

module.exports.handler = async function (event, context) {

    // Сохраняем контекст в глобальную переменную
    globalContext = context;

    const message = JSON.parse(event.body);
    await bot.handleUpdate(message);
    return {
        statusCode: 200,
        body: '',
    };
};

