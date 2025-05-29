import telebot
import requests
import csv
import time
import re
import json
import hashlib
from io import StringIO
from telebot import types

import os

bot = telebot.TeleBot(os.getenv("TELEGRAM_TOKEN"))  # Получить токен из переменной окружения
ADMIN_ID = os.getenv("TELEGRAM_ID")  # Получить id из переменной окружения

def load_anime_db():
    url = "https://docs.google.com/spreadsheets/d/10dD8Hhf-uVxuloE6yy0p8hdswbW7xGrNR_6otJTbKuA/export?format=csv&gid=0"
    response = requests.get(url)
    data = response.content.decode('utf-8')
    reader = csv.DictReader(StringIO(data))

    anime_db = {}
    for row in reader:
        anime = row['Anime']
        episode = row['Episode']
        dubbing = row['Dubbing Name']
        link = row['Link']

        if anime not in anime_db:
            anime_db[anime] = {}
        if episode not in anime_db[anime]:
            anime_db[anime][episode] = {}

        anime_db[anime][episode][dubbing] = link
    return anime_db

anime_db = load_anime_db()

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

callback_storage = {}
def create_short_id(long_string):
    hash_obj = hashlib.md5(long_string.encode())
    short_id = hash_obj.hexdigest()[:16]
    callback_storage[short_id] = long_string
    return short_id

def send_shikimori_info(chat_id, title, user_id=None):
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/114.0.0.0 Safari/537.36")
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
        description_raw = anime_details.get('description', 'Описание недоступно.')

        # --- Очищаем описание от HTML тегов ---
        import re
        description_text = re.sub(r'<[^>]+>', '', description_raw)  # удаляем все HTML теги

        # --- Удаляем всё после ключевого слова "Персонажи" или "Characters" для краткого описания ---
        cut_points = ['Персонажи', 'Characters', 'character', 'Персонаж', 'персонаж']
        short_description = description_text
        for point in cut_points:
            idx = short_description.find(point)
            if idx != -1:
                short_description = short_description[:idx].strip()
                break

        # Убираем пустые строки
        description_lines = [line.strip() for line in short_description.split('\n') if line.strip()]
        short_description_clean = "\n".join(description_lines)

        # Ограничим длину короткого описания для телеги (макс 600 символов)
        MAX_DESC_LEN = 600
        if len(short_description_clean) > MAX_DESC_LEN:
            short_description_clean = short_description_clean[:MAX_DESC_LEN].rsplit(' ', 1)[0] + "..."

        year = anime_details.get('aired_on')
        if year:
            year = year[:4]
        else:
            year = "Год неизвестен"

        image_info = anime_details.get('image')
        if image_info and image_info.get('original'):
            image_url = f"https://shikimori.one{image_info['original']}"
        else:
            image_url = None

        caption = f"🎬 <b>{title_ru}</b>\n📅 {year}\n\n📝 {short_description_clean}"

        # Сохраняем полное описание в callback_storage, если передан user_id
        # Для ключа используем md5 от названия и user_id, чтобы уникально
        full_desc_key = None
        if user_id:
            import hashlib
            key_str = f"fulldesc_{title}_{user_id}"
            key_hash = hashlib.md5(key_str.encode()).hexdigest()
            full_desc_key = key_hash
            callback_storage[full_desc_key] = description_text  # сохраняем полное описание (не очищенное)

        # Добавим кнопку "Показать полное описание" если user_id есть
        markup = None
        if full_desc_key:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("📝 Показать полное описание", callback_data=full_desc_key))

        if image_url:
            bot.send_photo(chat_id, photo=image_url, caption=caption, parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=markup)

        return True

    except Exception as e:
        print(f"Ошибка при получении данных с Shikimori: {e}")
        return False


@bot.callback_query_handler(func=lambda call: call.data in callback_storage)
def full_description_handler(call):
    # Выводим полное описание по ключу
    full_desc = callback_storage.get(call.data)
    if full_desc:
        # Ограничение в 4096 символов на сообщение, делим, если нужно
        MAX_MSG_LEN = 4000
        messages = [full_desc[i:i+MAX_MSG_LEN] for i in range(0, len(full_desc), MAX_MSG_LEN)]
        for msg in messages:
            bot.send_message(call.message.chat.id, msg, parse_mode="HTML")
        bot.answer_callback_query(call.id)
    else:
        bot.answer_callback_query(call.id, "Полное описание недоступно.", show_alert=True)

def generate_episode_keyboard(anime, episode, user_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    
    episodes = sorted(anime_db[anime].keys(), key=lambda x: int(x) if x.isdigit() else x)
    current_index = episodes.index(episode)
    
    # Кнопки навигации
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

    fav_text = "💔 Убрать из любимых" if anime in user_favs else "❤️ В избранное"
    fav_id = create_short_id(f"favtoggle_{anime}_{user_id}")
    markup.add(types.InlineKeyboardButton(fav_text, callback_data=fav_id))

    if anime in user_favs:
        notif_text = "🔕 Отключить уведомления" if anime in user_notifs else "🔔 Включить уведомления"
        notif_id = create_short_id(f"notiftoggle_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(notif_text, callback_data=notif_id))

    episodes = sorted(anime_db[anime].keys(), key=lambda x: int(x) if x.isdigit() else x)
    if episodes:
        first_ep_id = create_short_id(f"episode_{anime}|{episodes[0]}_{user_id}")
        markup.add(types.InlineKeyboardButton("▶️ Выбрать серию", callback_data=first_ep_id))

    return markup

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
        if anime_db:
            first_anime = next(iter(anime_db))
            send_notification(first_anime)
        time.sleep(3600)

@bot.message_handler(commands=['start'])
def start_message(message):
    user_id = message.from_user.id
    user_str_id = str(user_id)
    if user_str_id not in user_data:
        user_data[user_str_id] = {"favorites": [], "notifications": []}
        save_user_data()
    bot.send_message(
        message.chat.id,
        "👋 Привет! Я бот для поиска и просмотра аниме!\n\n"
        "Вот что я умею:\n"
        "🔍 Найду аниме по названию\n"
        "🎬 Покажу описание и картинку с Shikimori\n"
        "📺 Дам ссылки на серии с разными озвучками\n\n"
        "Просто напиши название аниме, и я всё сделаю сам 😊"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    user_str_id = str(user_id)
    data = call.data
    if data == "empty":
        bot.answer_callback_query(call.id)
        return
    if data not in callback_storage:
        bot.answer_callback_query(call.id, "Данные устарели, попробуйте снова.", show_alert=True)
        return
    full_data = callback_storage[data]
    parts = full_data.split('_', 1)
    action = parts[0]

    if action == "anime":
        m = re.match(r'anime_(.+)_(\d+)$', full_data)
        if not m or int(m.group(2)) != user_id:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name = m.group(1)
        if not send_shikimori_info(call.message.chat.id, anime_name):
            bot.send_message(call.message.chat.id, "Информация не найдена.")
        markup = generate_anime_keyboard(anime_name, user_id)
        bot.send_message(call.message.chat.id, f"🎬 <b>{anime_name}</b>", reply_markup=markup, parse_mode="HTML")
        bot.answer_callback_query(call.id)

    elif action == "episode":
        m = re.match(r'episode_(.+)\|(.+)_(\d+)$', full_data)
        if not m or int(m.group(3)) != user_id:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, episode = m.group(1), m.group(2)
        if anime_name not in anime_db or episode not in anime_db[anime_name]:
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return
        markup = generate_episode_keyboard(anime_name, episode, user_id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif action == "dubbing":
        m = re.match(r'dubbing_(.+)\|(.+)\|(.+)_(\d+)$', full_data)
        if not m or int(m.group(4)) != user_id:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, episode, dubbing_name = m.group(1), m.group(2), m.group(3)
        if (anime_name not in anime_db or episode not in anime_db[anime_name] or
                dubbing_name not in anime_db[anime_name][episode]):
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return
        link = anime_db[anime_name][episode][dubbing_name]
        bot.send_message(call.message.chat.id, f"Вот ссылка на {dubbing_name} для серии {episode}:\n{link}")
        bot.answer_callback_query(call.id)

    elif action == "favtoggle":
        m = re.match(r'favtoggle_(.+)_(\d+)$', full_data)
        if not m or int(m.group(2)) != user_id:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name = m.group(1)
        user_favs = user_data.setdefault(user_str_id, {}).setdefault('favorites', [])
        if anime_name in user_favs:
            user_favs.remove(anime_name)
            bot.answer_callback_query(call.id, f"{anime_name} удалено из избранного.")
        else:
            user_favs.append(anime_name)
            bot.answer_callback_query(call.id, f"{anime_name} добавлено в избранное.")
        save_user_data()
        markup = generate_anime_keyboard(anime_name, user_id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif action == "notiftoggle":
        m = re.match(r'notiftoggle_(.+)_(\d+)$', full_data)
        if not m or int(m.group(2)) != user_id:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name = m.group(1)
        user_notifs = user_data.setdefault(user_str_id, {}).setdefault('notifications', [])
        if anime_name in user_notifs:
            user_notifs.remove(anime_name)
            bot.answer_callback_query(call.id, f"Уведомления для {anime_name} отключены.")
        else:
            user_notifs.append(anime_name)
            bot.answer_callback_query(call.id, f"Уведомления для {anime_name} включены.")
        save_user_data()
        markup = generate_anime_keyboard(anime_name, user_id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

    else:
        bot.answer_callback_query(call.id, "Неизвестное действие.", show_alert=True)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    query = message.text.strip().lower()
    matched_anime = [a for a in anime_db if query in a.lower()]
    if not matched_anime:
        success = send_shikimori_info(message.chat.id, query)
        if success:
            bot.send_message(message.chat.id,
                f"⚠️ Этого аниме нет в базе бота.\nЕсли хотите, чтобы его добавили, напишите сюда: @{ADMIN_ID}")
        else:
            bot.send_message(message.chat.id, "Аниме не найдено.")
        return
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup()
    for anime in matched_anime:
        btn_id = create_short_id(f"anime_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(anime, callback_data=btn_id))
    bot.send_message(message.chat.id, "Выбери аниме:", reply_markup=markup)

if __name__ == "__main__":
    print("Бот запущен")
    bot.polling(none_stop=True)
