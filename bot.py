import os
import telebot

TOKEN = os.getenv('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=['start'])
def send_start(message):
    bot.reply_to(message, 'Привет! Я твой бот. Попробуй /help')

@bot.message_handler(commands=['help'])
def send_help(message):
    bot.reply_to(message, 'Доступные команды:\n/start — приветствие\n/echo — повторит твоё сообщение\n/ping — проверка связи')

@bot.message_handler(commands=['ping'])
def send_ping(message):
    bot.reply_to(message, 'PONG! Бот онлайн ✅')

@bot.message_handler(commands=['echo'])
def send_echo_prompt(message):
    msg = bot.send_message(message.chat.id, 'Отправь любое сообщение — я повторю:')
    bot.register_next_step_handler(msg, process_echo)

def process_echo(message):
    bot.reply_to(message, f'Ты написал: {message.text}')

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.reply_to(message, 'Я пока не знаю такой команды. Попробуй /help')

bot.infinity_polling()
