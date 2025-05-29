nd(types.InlineKeyboardButton("▶️", callback_data=next_id))
    else:
        buttons.append(types.InlineKeyboardButton(" ", callback_data="empty"))

    markup.row(*buttons)

    # Кнопки выбора озвучки для текущей серии
    for dubbing_name in anime_db[anime][current_episode]:
        dubbing_data = f"dubbing_{anime}|{current_episode}|{dubbing_name}_{user_id}"
        short_id = create_short_id(dubbing_data)
        markup.add(types.InlineKeyboardButton(dubbing_name, callback_data=short_id))

    return markup

def generate_anime_keyboard(anime, user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)

    user_str_id = str(user_id)
    user_favs = set(user_data.get(user_str_id, {}).get('favorites', []))
    user_notifs = set(user_data.get(user_str_id, {}).get('notifications', []))

    if anime in user_favs:
        fav_text = "💔 Убрать из любимых"
    else:
        fav_text = "❤️ В избранное"

    fav_id = create_short_id(f"favtoggle_{anime}_{user_id}")
    markup.add(types.InlineKeyboardButton(fav_text, callback_data=fav_id))

    if anime in user_favs:
        if anime in user_notifs:
            notif_text = "🔕 Отключить уведомления"
        else:
            notif_text = "🔔 Включить уведомления"
        notif_id = create_short_id(f"notiftoggle_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(notif_text, callback_data=notif_id))

    episodes = sorted(anime_db[anime].keys(), key=lambda x: int(x) if x.isdigit() else x)
    if episodes:
        first_ep_id = create_short_id(f"episode_{anime}|{episodes[0]}_{user_id}")
        markup.add(types.InlineKeyboardButton("▶️ Выбрать серию", callback_data=first_ep_id))

    return markup

def send_notification(anime):
    """Отправить уведомления всем подписанным на anime пользователям"""
    sent_count = 0
    for user_str_id, data_dict in user_data.items():
        if anime in data_dict.get('notifications', []):
            try:
                bot.send_message(int(user_str_id), f"🔔 Новая серия доступна для аниме: <b>{anime}</b>!", parse_mode="HTML")
                sent_count += 1
            except Exception as e:
                print(f"Ошибка отправки уведомления {user_str_id}: {e}")
    return sent_count

def periodic_check():
    """Пример функции для периодической проверки новых серий и отправки уведомлений"""
    while True:
        # Здесь должна быть логика проверки новых серий на источнике
        # Для примера: отправим уведомления для первого аниме из базы
        if anime_db:
            first_anime = next(iter(anime_db))
            send_notification(first_anime)
        time.sleep(3600)  # Проверять каждый час

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
    global callback_storage

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

    # Формат: action_anime[_episode][_dubbing]_userId
    parts = full_data.split('_', 1)
    action = parts[0]

    if action == "anime":
        # full_data: anime_AnimeName_userId
        m = re.match(r'anime_(.+)_(\d+)$', full_data)
        if not m:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, uid = m.group(1), m.group(2)
        if int(uid) != user_id:
            bot.answer_callback_query(call.id, "Это не для вас.", show_alert=True)
            return

        # Сначала отправляем описание с картинкой
        if not send_shikimori_info(call.message.chat.id, anime_name):
            bot.send_message(call.message.chat.id, "Информация не найдена.")
        
        # Затем отправляем кнопки управления в новом сообщении
        markup = generate_anime_keyboard(anime_name, user_id)
        bot.send_message(call.message.chat.id, f"🎬 <b>{anime_name}</b>", reply_markup=markup, parse_mode="HTML")
        bot.answer_callback_query(call.id)

    elif action == "episode":
        # full_data: episode_AnimeName|Episode_userId
        m = re.match(r'episode_(.+)\|(.+)_(\d+)$', full_data)
        if not m:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, episode, uid = m.group(1), m.group(2), m.group(3)
        if int(uid) != user_id:
            bot.answer_callback_query(call.id, "Это не для вас.", show_alert=True)
            return

        if anime_name not in anime_db or episode not in anime_db[anime_name]:
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return

        markup = generate_episode_keyboard(anime_name, episode, user_id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)

    elif action == "dubbing":
        # full_data: dubbing_AnimeName|Episode|Dubbing_userId
        m = re.match(r'dubbing_(.+)\|(.+)\|(.+)_(\d+)$', full_data)
        if not m:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, episode, dubbing_name, uid = m.group(1), m.group(2), m.group(3), m.group(4)
        if int(uid) != user_id:
            bot.answer_callback_query(call.id, "Это не для вас.", show_alert=True)
            return

        if (anime_name not in anime_db or episode not in anime_db[anime_name] or
                dubbing_name not in anime_db[anime_name][episode]):
            bot.answer_callback_query(call.id, "Данные не найдены.", show_alert=True)
            return

        link = anime_db[anime_name][episode][dubbing_name]
        bot.send_message(call.message.chat.id, f"Вот ссылка на {dubbing_name} для серии {episode}:\n{link}")
        bot.answer_callback_query(call.id)

    elif action == "favtoggle":
        # full_data: favtoggle_AnimeName_userId
        m = re.match(r'favtoggle_(.+)_(\d+)$', full_data)
        if not m:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, uid = m.group(1), m.group(2)
        if int(uid) != user_id:
            bot.answer_callback_query(call.id, "Это не для вас.", show_alert=True)
            return

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
        # full_data: notiftoggle_AnimeName_userId
        m = re.match(r'notiftoggle_(.+)_(\d+)$', full_data)
        if not m:
            bot.answer_callback_query(call.id, "Неверные данные.", show_alert=True)
            return
        anime_name, uid = m.group(1), m.group(2)
        if int(uid) != user_id:
            bot.answer_callback_query(call.id, "Это не для вас.", show_alert=True)
            return

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
                             f"⚠️ Этого аниме нет в базе бота.\n"
                             f"Если хотите, чтобы его добавили, напишите сюда: @{ADMIN_ID}")
        else:
            bot.send_message(message.chat.id, "Аниме не найдено.")
        return

    # Если найдено аниме в базе
    user_id = message.from_user.id
    markup = types.InlineKeyboardMarkup()
    for anime in matched_anime:
        btn_id = create_short_id(f"anime_{anime}_{user_id}")
        markup.add(types.InlineKeyboardButton(anime, callback_data=btn_id))

    bot.send_message(message.chat.id, "Выбери аниме:", reply_markup=markup)

if __name__ == "__main__":
    # Опционально можно запустить периодическую проверку уведомлений в отдельном потоке
    # threading.Thread(target=periodic_check, daemon=True).start()

    print("Бот запущен")
    bot.polling(none_stop=True)
