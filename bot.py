import os
import re
import time
import json
import hashlib
import requests
import csv
from io import StringIO
from telebot import TeleBot, types

# ----------------------------------------
# Инициализация бота и константы
bot = TeleBot(os.getenv("TELEGRAM_TOKEN"))  # Токен из переменной окружения
ADMIN_ID = os.getenv("TELEGRAM_ID")         # ID администратора (если нужен)

# ----------------------------------------
# Загрузка и обработка базы аниме из Google Sheets (CSV)
def load_anime_db():
    url = "https://docs.google.com/spreadsheets/d/10dD8Hhf-uVxuloE6yy0p8hdswbW7xGrNR_6otJTbKuA/export?format=csv&gid=0"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.content.decode('utf-8')
        reader = csv.DictReader(StringIO(data))

        anime_db = {}
        for row in reader:
            anime = row['Anime']
            episode = row['Episode']
            dubbing = row['Dubbing Name']
            link = row['Link']

            anime_db.setdefault(anime, {}).setdefault(episode, {})[dubbing] = link
        return anime_db
    except Exception as e:
        print(f"Ошибка при загрузке базы аниме: {e}")
        return {}

anime_db = load_anime_db()

# ----------------------------------------
# Работа с данными пользователей
def load_user_data():
    try:
        with open('user_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_user_data():
    with open('user_data.json', 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

user_data = load_user_data()

# ----------------------------------------
# Хранилище callback данных для кнопок
callback_storage = {}

def create_short_id(long_string):
    hash_obj = hashlib.md5(long_string.encode())
    short_id = hash_obj.hexdigest()[:16]
    callback_storage[short_id] = long_string
    return short_id

# ----------------------------------------
# Получение информации с Shikimori API
def send_shikimori_info(chat_id, title):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        )
    }
    retries = 2
    timeout_sec = 15

    def request_with_retry(url):
        last_exception = None
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=headers, timeout=timeout_sec)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                last_exception = e
                print(f"Попытка {attempt + 1} не удалась: {e}")
                time.sleep(1)
        raise last_exception

    try:
        search_url = f"https://shikimori.one/api/animes?search={title}"
        response = request_with_retry(search_url)
        data = response.json()

        if not data:
            return False

        anime = data[0]
        anime_id = anime.get('id')
        if not anime_id:
            return False

        details_url = f"https://shikimori.one/api/animes/{anime_id}"
        details_response = request_with_retry(details_url)
        anime_details = details_response.json()

        # Если нет русского названия, пробуем альтернативный поиск по английскому имени
        if not anime_details.get('russian') and anime_details.get('name'):
            alt_search_url = f"https://shikimori.one/api/animes?search={anime_details['name']}"
            alt_response = request_with_retry(alt_search_url)
            alt_data = alt_response.json()
            if alt_data:
                anime = alt_data[0]
                anime_id = anime.get('id')
                if anime_id:
                    details_url = f"https://shikimori.one/api/animes/{anime_id}"
                    details_response = request_with_retry(details_url)
                    anime_details = details_response.json()

        title_ru = anime_details.get('russian') or anime_details.get('name') or "Без названия"
        description = anime_details.get('description', 'Описание недоступно.').replace('<br>', '\n')
        year = anime_details.get('aired_on')
        year = year[:4] if year else "Год неизвестен"

        image_info = anime_details.get('image')
        image_url = f"https://shikimori.one{image_info['original']}" if image_info and image_info.get('original') else None

        caption = f"🎬 <b>{title_ru}</b>\n📅 {year}\n\n📝 {description}"

        if image_url:
            bot.send_photo(chat_id, photo=image_url, caption=caption, parse_mode="HTML")
        else:
            bot.send_message(chat_id, caption, parse_mode="HTML")

        return True
    except Exception as e:
        print(f"Ошибка при получении данных с Shikimori: {e}")
        return False

# ----------------------------------------
# Генерация клавиатур для выбора серии и аниме
def generate_episode_keyboard(anime, episode, user_id):
    markup = types.InlineKeyboardMarkup(row_width=3)

    episodes = sorted(anime_db[anime].keys(), key=lambda x: int(x) if x.isdigit() else x)
    current_index = episodes.index(episode)

    # Кнопки навигации между эпизодами
    nav_buttons = []
    if current_index > 0:
        prev_ep = episodes[current_index - 1]
        prev_id = create_short_id(f"episode_{anime}|{prev_ep}_{user_id}")
        nav_buttons.append(types.InlineKeyboardButton("⬅️", callback_data=prev_id))
    else:
        nav_buttons.append(types.InlineKeyboardButton(" ", callback_data="empty"))

    nav_buttons.append(types.InlineKeyboardButton(f"Серия {episode}", callback_data="empty"))

    if current_index < len(episodes) - 1:
        next_ep = episodes[current_index + 1]
        next_id = create_short_id(f"episode_{anime}|{next_ep}_{user_id}")
        nav_buttons.append(types.InlineKeyboardButton("➡️", callback_data=next_id))
    else:
        nav_buttons.append(types.InlineKeyboardButton(" ", callback_data="empty"))

    markup.row(*nav_buttons)

    # Кнопки озвучек
    for dubbing_name in anime_db[anime][episode]:
        dub_id = create_short_id(f"dubbing_{anime}|{episode}|{dubbing_name}_{user_id}")
        markup.add(types.InlineKeyboardButton(dubbing_name, callback_data=dub_id))

    # Кнопка "Назад к аниме"
    back_id = create_short_id(f"anime_{anime}_{user_id}")
    markup.add(types.InlineKeyboardButton("🔙 Назад к аниме", callback_data=back_id))

    return markup

def generate_anime_keyboard(anime, user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    user_str_id = str(user_id)
    user_favs = set(user_data.get(user_str_id, {}).get('favorites', []))
    user_notifs = set(user_data.get(user_str_id, {}).get('notifications', []))

    # Кнопка "Избранное / Убрать из избранного"
    fav_text = "💔 Убрать из любимых" if anime in user_favs else "❤️ В избранное"
    fav_id = create_short_id(f"favtoggle_{anime}_{user_id}")
    markup.add(types.InlineKeyboardButton(fav_text, callback_data=fav_id))

    # Кнопка уведомлений, если в избранном
    if anime in user_favs:
        notif_text = "🔕 Отключить уведомления" if anime in user_notifs else "🔔 Включить уведомления"
        notif_id = create_short_id(f"notiftoggle_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(notif_text, callback_data=notif_id))

    # Кнопка для выбора серии (первая по порядку)
    episodes = sorted(anime_db[anime].keys(), key=lambda x: int(x) if x.isdigit() else x)
    if episodes:
        first_ep_id = create_short_id(f"episode_{anime}|{episodes[0]}_{user_id}")
        markup.add(types.InlineKeyboardButton("▶️ Выбрать серию", callback_data=first_ep_id))

    return markup

# ----------------------------------------
# Уведомления пользователей о новых сериях (можно запускать в фоне)
def send_notification(anime):
    sent_count = 0
    for user_str_id, data_dict in user_data.items():
        if anime in data_dict.get('notifications', []):
            try:
                bot.send_message(int(user_str_id), f"🔔 Новая серия доступна для аниме: <b>{anime}</b>!", parse_mode="HTML")
                sent_count += 1
            except Exception:
                pass
    return sent_count

def periodic_check():
    while True:
        try:
            new_db = load_anime_db()
            # Здесь можно реализовать логику сравнения с предыдущей версией anime_db для определения новых серий
            # Если есть новые серии, отправлять уведомления через send_notification()
            # Обновляем глобальную базу
            global anime_db
            anime_db = new_db
        except Exception as e:
            print(f"Ошибка при периодической проверке: {e}")
        time.sleep(900)  # Проверять каждые 15 минут

# ----------------------------------------
# Обработчики команд и сообщений

@bot.message_handler(commands=["start"])
def start_message(message):
    user_id = str(message.from_user.id)
    user_data.setdefault(user_id, {"favorites": [], "notifications": []})
    save_user_data()

    text = (
        "Привет! Я — бот для просмотра аниме.\n"
        "Введите название аниме для поиска или воспользуйтесь меню."
    )
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=["help"])
def help_message(message):
    help_text = (
        "📖 Команды бота:\n"
        "/start - начать работу с ботом\n"
        "Введите название аниме для поиска\n"
        "Используйте кнопки для выбора серии и озвучки."
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(func=lambda m: True)
def handle_anime_search(message):
    user_id = str(message.from_user.id)
    query = message.text.strip()

    # Поиск совпадений в anime_db по названию (регистронезависимо)
    found_animes = [anime for anime in anime_db.keys() if query.lower() in anime.lower()]

    if not found_animes:
        # Попробуем получить инфо с Shikimori API
        if send_shikimori_info(message.chat.id, query):
            return
        bot.send_message(message.chat.id, "Аниме не найдено. Попробуйте другое название.")
        return

    # Если найдено много аниме — предложить выбор
    markup = types.InlineKeyboardMarkup(row_width=1)
    for anime in found_animes:
        anime_id = create_short_id(f"anime_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(anime, callback_data=anime_id))
    bot.send_message(message.chat.id, "Выберите аниме:", reply_markup=markup)

# ----------------------------------------
# Обработка нажатий на кнопки
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = str(call.from_user.id)
    data = call.data

    if data == "empty":
        bot.answer_callback_query(call.id)
        return

    long_data = callback_storage.get(data)
    if not long_data:
        bot.answer_callback_query(call.id, "Истёк срок действия кнопки. Попробуйте снова.")
        return

    # Разбор длинных данных
    if long_data.startswith("anime_"):
        # Выбрано аниме — показать клавиатуру с сериями и настройками
        anime = long_data[len("anime_"):].rsplit("_", 1)[0]
        markup = generate_anime_keyboard(anime, call.from_user.id)
        bot.edit_message_text(f"Вы выбрали аниме: <b>{anime}</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif long_data.startswith("episode_"):
        # Выбор серии
        match = re.match(r"episode_(.+)\|(.+)_(\d+)", long_data)
        if not match:
            bot.answer_callback_query(call.id, "Ошибка данных.")
            return
        anime, episode, uid = match.groups()
        markup = generate_episode_keyboard(anime, episode, int(uid))
        bot.edit_message_text(f"Вы выбрали серию <b>{episode}</b> аниме <b>{anime}</b>", call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif long_data.startswith("dubbing_"):
        # Выбор озвучки - отправка ссылки
        match = re.match(r"dubbing_(.+)\|(.+)\|(.+)_(\d+)", long_data)
        if not match:
            bot.answer_callback_query(call.id, "Ошибка данных.")
            return
        anime, episode, dubbing, uid = match.groups()
        link = anime_db.get(anime, {}).get(episode, {}).get(dubbing)
        if link:
            bot.send_message(call.message.chat.id, f"Ссылка на {anime} серия {episode} ({dubbing}):\n{link}")
        else:
            bot.send_message(call.message.chat.id, "Ссылка не найдена.")
        bot.answer_callback_query(call.id)

    elif long_data.startswith("favtoggle_"):
        # Добавить или убрать из избранного
        anime = long_data[len("favtoggle_"):].rsplit("_", 1)[0]
        favs = user_data.setdefault(user_id, {}).setdefault("favorites", [])
        if anime in favs:
            favs.remove(anime)
            bot.answer_callback_query(call.id, f"Удалено из избранного: {anime}")
        else:
            favs.append(anime)
            bot.answer_callback_query(call.id, f"Добавлено в избранное: {anime}")
        save_user_data()
        # Обновить клавиатуру
        markup = generate_anime_keyboard(anime, int(user_id))
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif long_data.startswith("notiftoggle_"):
        # Включить/отключить уведомления
        anime = long_data[len("notiftoggle_"):].rsplit("_", 1)[0]
        notifs = user_data.setdefault(user_id, {}).setdefault("notifications", [])
        if anime in notifs:
            notifs.remove(anime)
            bot.answer_callback_query(call.id, f"Уведомления отключены для: {anime}")
        else:
            notifs.append(anime)
            bot.answer_callback_query(call.id, f"Уведомления включены для: {anime}")
        save_user_data()
        markup = generate_anime_keyboard(anime, int(user_id))
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

    else:
        bot.answer_callback_query(call.id, "Неизвестное действие.")

# ----------------------------------------
# Запуск бота
if __name__ == "__main__":
    print("Бот запущен.")
    bot.infinity_polling()
