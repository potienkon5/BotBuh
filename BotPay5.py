import telebot
import stripe
import threading
import time
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# Инициализация Flask приложения и бота
app = Flask(__name__)
bot = telebot.TeleBot('7866110241:AAEMk7X2Kkr-TKhoB1QrdL2UBfCCfN8mHMY')
stripe.api_key = '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'

# Подключение к базе данных
conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('DROP TABLE IF EXISTS users')
cursor.execute('''CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    phone_number TEXT,
    expiration TEXT
)''')
cursor.execute("PRAGMA table_info(users)")
print(cursor.fetchall())
conn.commit()

admin_id = 920716848  # Замените на числовой ID администратора
admin_id2 = 951610426
CHANNEL_ID = "-1001709871902"  # Замените на chat_id вашего канала

PRICES = {1: 2, 6: 10, 12: 20}  # Цены подписок

@app.route('/stripe_webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_z9DPMCBDw5GazR6nk8KMw8VV97hjtg12'
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        print(f"Webhook error: {e}")
        return 'Error', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = int(session['metadata']['user_id'])
        duration = float(session['metadata']['duration'])
        expiration_date = datetime.now() + (timedelta(minutes=3) if duration == 0.002083 else timedelta(days=30 * duration))
        
        cursor.execute('UPDATE users SET expiration = ? WHERE user_id = ?', (expiration_date.isoformat(), user_id))
        conn.commit()

        # Получение номера телефона из базы
        cursor.execute('SELECT phone_number FROM users WHERE user_id = ?', (user_id,))
        phone_result = cursor.fetchone()
        phone_number = phone_result[0] if phone_result else "не указан"

         # Уведомление пользователя и админа
        message = f"Оплата успешна! Вы получили доступ на {int(duration * 30)} месяц(ев)." if duration != 0.002083 else "Вы получили тест доступ на 3 минут."
        bot.send_message(user_id, message)
        user_info = bot.get_chat(user_id)
        username = user_info.username or f"user?id={user_id}"
        admin_message = f"Пользователь с номером +{phone_number} оплатил подписку на {int(duration * 30) if duration != 0.002083 else 'тест 3 минут'}."
        bot.send_message(admin_id, admin_id2, admin_message)

        if duration == 0.002083:
            threading.Thread(target=remove_user_after_timeout, args=(user_id, 60)).start()

    return jsonify(success=True), 200

@bot.message_handler(commands=['start'])
def start_command(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    phone_button = telebot.types.KeyboardButton("Поделиться номером телефона", request_contact=True)
    markup.add(phone_button)
    bot.send_message(message.chat.id, """
Привет👋🏻

Чтобы получить доступ к телеграм-каналу: "Бухгалтер в Германии"🇩🇪 необходимо внести оплату.

Для получения доступа к подписке, пожалуйста, поделитесь своим номером телефона.                        
                     """, reply_markup=markup)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    if message.contact:
        phone_number = message.contact.phone_number
        user_id = message.from_user.id

        # Сохранение номера телефона в базу данных
        cursor.execute('INSERT OR REPLACE INTO users (user_id, phone_number, expiration) VALUES (?, ?, ?)',
                       (user_id, phone_number, None))
        conn.commit()

        # Переход к выбору подписки
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("Оплатить подписку", callback_data="subscribe"))
        bot.send_message(
            message.chat.id,
            "Спасибо! Теперь выберите срок действия подписки.",
            reply_markup=markup
        )
    else:
        bot.send_message(message.chat.id, "Пожалуйста, используйте кнопку 'Поделиться номером телефона'.")

@bot.callback_query_handler(func=lambda call: call.data == "subscribe")
def subscribe_command(call):
    # Проверка, есть ли номер телефона у пользователя
    user_id = call.message.chat.id
    cursor.execute('SELECT phone_number FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()

    if result and result[0]:  # Если номер телефона существует
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("1 месяц (2 евро)", callback_data="1"))
        markup.add(telebot.types.InlineKeyboardButton("6 месяцев (10 евро)", callback_data="6"))
        markup.add(telebot.types.InlineKeyboardButton("1 год (20 евро)", callback_data="12"))
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Выберите срок подписки:", reply_markup=markup)
    else:
        bot.send_message(
            user_id,
            "Пожалуйста, сначала поделитесь своим номером телефона. Нажмите /start, чтобы начать заново."
        )

@bot.callback_query_handler(func=lambda call: call.data in ["1", "6", "12"])
def payment_process(call):
    duration = float(call.data)
    price = PRICES[duration]
    user_id = call.message.chat.id

    # Создание сессии Stripe
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'eur',
                'product_data': {'name': f'Подписка на {int(duration * 30) if duration != 0.002083 else 1} {("3 минут" if duration == 0.002083 else "месяц(ев)")}'},
                'unit_amount': int(price * 100),
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url='https://t.me/+nF4uweCl7aVhMWQy',
        cancel_url='https://t.me/pay_chanel_bot',
        metadata={'user_id': user_id, 'duration': duration}
    )

    # Сохранение данных сессии для отслеживания отмененной оплаты
    pending_payments[user_id] = {'session_id': session.id, 'start_time': time.time()}

    # Создание кнопки оплаты
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Оплатить", url=session.url))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Перейдите по ссылке для оплаты.", reply_markup=markup)

    # Таймер для проверки завершения оплаты
    threading.Thread(target=check_payment_status, args=(user_id,)).start()

# Словарь для отслеживания платежей
pending_payments = {}

def check_payment_status(user_id):
    # Ожидание времени на оплату (например, 5 минут)
    time.sleep(350000)  # 150 секунд = 2,5 минуты

    # Проверка, осталась ли запись в `pending_payments`
    if user_id in pending_payments:
        session_id = pending_payments[user_id]['session_id']
        
        # Проверка статуса сессии в Stripe
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status == 'paid':
                # Если платеж завершен, удаляем запись и выходим
                print(f"Платеж для пользователя {user_id} завершен.")
                del pending_payments[user_id]
                return
        except Exception as e:
            print(f"Ошибка проверки статуса оплаты в Stripe: {e}")

        # Если платеж не завершен, отправляем сообщение пользователю
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("Оплатить подписку", callback_data="subscribe"))
        bot.send_message(user_id, """
Возможно Вас отвлекли?🤔

Вы хотели получить доступ к телеграм-каналу: "Бухгалтер в Германии"

Выберите срок действия вашей подписки на канал и нажмите: "оплатить":⬇️
        """, reply_markup=markup)

        # Удаление записи из `pending_payments`
        del pending_payments[user_id]

# Удаление пользователя по истечении подписки
def remove_user_after_timeout(user_id, minutes):
    time.sleep(minutes * 60)
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()

# Запуск напоминания в отдельном потоке
def remind_users(func=lambda call: call.data == "subscribe"):
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Оплатить подписку", callback_data="subscribe"))    
    while True:
        cursor.execute('SELECT user_id, expiration, phone_number FROM users')
        for user_id, expiration, phone_number in cursor.fetchall():
            if expiration:  # Проверяем, что expiration не None
                try:
                    expiration_date = datetime.fromisoformat(expiration)
                    time_left = (expiration_date - datetime.now()).total_seconds()
                    days_left = (expiration_date - datetime.now()).days

                    if days_left == 3:
                        bot.send_message(user_id, """
Через 3 дня у вас завершится 
  доступ к телеграм-каналу: 
   "Бухгалтер в Германии"

         Продлить⬇️
                        """, reply_markup=markup)
                    elif days_left == 1:
                        bot.send_message(user_id, """
Завтра у вас завершится доступ 
 к телеграм-каналу: "Бухгалтер 
         в Германии"

         Продлить⬇️
                        """, reply_markup=markup)
                    elif 0 < time_left <= 3600:
                        bot.send_message(user_id, """
Ваш доступ истек. 😱

Продлим подписку?⬇️
                        """, reply_markup=markup)
                        notify_admin_of_expiration(user_id, phone_number)
                    elif time_left <= 0:
                        bot.send_message(user_id, """
Ваш доступ истек. 😱

Продлим подписку?⬇️
                        """, reply_markup=markup)
                        notify_admin_of_expiration(user_id, phone_number)
                        try:
                            # Удаление пользователя из канала
                            bot.kick_chat_member(CHANNEL_ID, user_id)
                            print(f"Пользователь {user_id} удален из канала {CHANNEL_ID}")
                        except Exception as e:
                            print(f"Ошибка при удалении пользователя {user_id} из канала: {e}")
                        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                        conn.commit()
                except ValueError:
                    print(f"Некорректное значение expiration для пользователя {user_id}: {expiration}")
            else:
                print(f"Пропущен пользователь {user_id}, так как expiration отсутствует")
        time.sleep(300)  # Проверка каждые 5 минут

def notify_admin_of_expiration(user_id, phone_number):
    user_info = bot.get_chat(user_id)
    username = user_info.username or f"user?id={user_id}"
    admin_message = f"Подписка у пользователя с номером +{phone_number} и username @{username} истекла."
    bot.send_message(admin_id, admin_id2, admin_message)

def run_bot():
    bot.remove_webhook()
    bot.polling(none_stop=True)

if __name__ == '__main__':
    threading.Thread(target=run_bot).start()
    threading.Thread(target=remind_users, daemon=True).start()
    app.run(port=5000)
