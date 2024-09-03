import pandas as pd
import base64
import requests
import glob
import json
import os
import shutil
import asyncio
import logging
import sys
from os import getenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import InputFile, Message
from aiogram.utils.markdown import hbold
import zipfile
import time
from aiogram.types import FSInputFile
import gspread
import telebot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup










TOKEN = ''

dp = Dispatcher()

file_path = 'dict.xlsx'
df = pd.read_excel(file_path)
result_dict = {col: df[col].dropna().apply(lambda x: x.replace('\xa0', '')).tolist() for col in df.columns}
api_key = ""
UPLOAD_DIRECTORY = 'images'
storage = MemoryStorage()

gc = gspread.service_account(filename='credentials.json')

class Form(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()



if not os.path.exists(UPLOAD_DIRECTORY):
    os.makedirs(UPLOAD_DIRECTORY)


def create_excel_from_images(images):
    df = pd.DataFrame(images)
    df.to_excel("result.xlsx", index=False)

def clear_directory(directory):
    for filename in os.listdir(directory):
        file_path = os.path.join(directory, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f'Failed to delete {file_path}. Reason: {e}')

def clear_result_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


async def save_and_unzip(bot: Bot, file: types.Document):
    file_info = await bot.get_file(file.file_id)
    file_path = os.path.join(UPLOAD_DIRECTORY, file.file_unique_id + ".zip")
    await bot.download_file(file_info.file_path, destination=file_path, timeout=99999)

    with zipfile.ZipFile(file_path, 'r') as zip_ref:
        zip_ref.extractall(UPLOAD_DIRECTORY)
    os.remove(file_path)

@dp.message(CommandStart())
async def send_welcome(message: types.Message, state: FSMContext):
    await message.answer("Будь ласка відправте артикул")
    await state.set_state(Form.waiting_for_text)



@dp.message(Form.waiting_for_text)
async def process_text(message: types.Message, state: FSMContext):
    if message.text.lower() in ['назад', 'завершить']:
        await message.answer("Будь ласка відправте артикул")
        return

    await state.update_data(text=message.text)
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Назад")],
            [KeyboardButton(text="Завершити")]
        ],
        resize_keyboard=True
    )

    await message.answer("Тепер одним  відправте фото", reply_markup=keyboard)
    await state.set_state(Form.waiting_for_photo)










@dp.message(Form.waiting_for_photo, F.photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    text = data.get('text')

    folder_path = os.path.join('images', text)
    os.makedirs(folder_path, exist_ok=True)
    largest_photo = message.photo[-1]
    file_id = largest_photo.file_id
    file_path = os.path.join(folder_path, f"{file_id}.jpg")
    await bot.download(file_id, destination=file_path)
    await message.answer("Відправте ще фото або завершіть сесію")






@dp.message(Form.waiting_for_photo)
async def go_back(message: types.Message, state: FSMContext):
    if message.text:
        if message.text.lower() == 'назад':
            await message.answer("Будь ласка відправте артикул")
            await state.set_state(Form.waiting_for_text)
        elif message.text.lower() == 'завершити':
            sent_message = await message.answer("Фото збережені")
            message_id = sent_message.message_id
            result = label_images(message_id,message.chat.id)
            sheet = gc.open_by_url('https://docs.google.com/spreadsheets/d/10mMLRBa4hunmI2gYBfqHip7VQETD7mkC--Yrv30Z67E/edit?gid=0#gid=0').sheet1
            sheet.append_rows(result, value_input_option="RAW")
            await message.answer("Результат додано в таблицю!", reply_markup=types.ReplyKeyboardRemove())
            clear_directory('images/')
            await state.clear()
            await message.answer("Будь ласка відправте артикул")
            await state.set_state(Form.waiting_for_text)







@dp.message(F.document.mime_type == 'application/zip')
async def handle_docs(message: types.Message, bot: Bot):
    await save_and_unzip(bot, message.document)
    sent_message = await message.answer("Файл успішно збережений, починаю обробку GPT")
    message_id = sent_message.message_id
    result = label_images(message_id,message.chat.id)
    sheet = gc.open_by_url('https://docs.google.com/spreadsheets/d/10mMLRBa4hunmI2gYBfqHip7VQETD7mkC--Yrv30Z67E/edit?gid=0#gid=0').sheet1
    sheet.append_rows(result, value_input_option="RAW")
    await message.answer("Результат додано в таблицю!")
    clear_directory('images/')




def list_images_in_dir(directory):
    image_extensions = ('*.png', '*.jpg', '*.jpeg')

    def get_images_from_directory(dir_path):
        images = []
        for extension in image_extensions:
            images.extend(glob.glob(os.path.join(dir_path, extension)))

        base64_images = []
        for image in images:
            with open(image, "rb") as image_file:
                base64_images.append(base64.b64encode(image_file.read()).decode('utf-8'))
        return base64_images

    all_images = []
    for root, dirs, files in os.walk(directory):
        if dirs:
            for sub_dir in dirs:
                sub_dir_path = os.path.join(root, sub_dir)
                base64_images = get_images_from_directory(sub_dir_path)
                all_images.append({
                    "dir": sub_dir,
                    "base": base64_images
                })
    return all_images

def label_images(message_id,chat_id):
    help_bot = telebot.TeleBot(TOKEN)
    result_list = []
    directory_path = 'images/'
    image_files = list_images_in_dir(directory_path)
    x = 0
    help_bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f'Зроблено {x}/{len(image_files)}')
    for image_set in image_files:
        articule = image_set.get('dir')
        image_set = image_set.get('base')
        gpt_images = [{
            "type": "text",
            "text": f"""Return raw json answer!!!! Отправляй только один json словарь,НИЧЕГО ДРУГОГО,НИКАКИХ ВЛОЖЕНЫХ СЛОВАРЕЙ И ТД,ЭТО ВЫЗЫВАЕТ ОШИБКУ!!!!\
                Нужно распознать по этим трем фото что это за вещь и пролейблить вот эти поля,пожалуйста попробуй найти максимум информации,\
                    используй коды которые есть на бирках\
                        ,используй информацию полученую на бирках и с фото,а так же интернет чтобы найти страну изготовителя и колецию,колекция так же может означать модель этого товара,это очень важно получить эти поля,можно использовать ключ-значениея только из этого списка и \
                            только из него,если невозможно определить - ставь None {result_dict}\
                            В поле Pattern не должно быть None - выбери наиболее подходящий.Так же в колекции может быть или название колекции или None.Получи максимум информации любыми путями\
                                найди фото на котором будет бирка и что то похожее на штрихкод- назови его code и добавь в список,найди на фото бирки что то что могло бы быть артикулом назови его -articule, а так же название вещи - назови ее name\
                                    ВОТ ПРИМЕР JSON,ОН ДОЛЖЕН БЫТЬ ШАБЛОННЫМ,ТОЛЬКО ТАКОЙ ОТВЕТ И ВСЕ НО С ДРУГИМИ ДАННЫМИ!!! ТОЛЬКО СЛОВАРЬ,ТОЛЬКО ЭТОТ ПРИМЕР,БОЛЬШЕ НИЧЕГО,НЕ СПИСКОВ,НЕ СЛОВАРЯ В СЛОВАРЕ,У МЕНЯ ИЗ-ЗА ЭТОГО СЛОМАЕТЬСЯ СКРИПТ!!!! \
                                        'name': '', 'articule': '', 'code': '', 'Size': '', 'Color': '', 'Pattern': '', 'Category': '', 'Seasonality': '', 'Style': '', 'Gender': '', 'Сompound': '', 'Brand': '', 'Collection': '', 'Country of manufacture': 'Китай',\
                                            используй только ЭТИ НАЗВАНИЯ,НЕ ИСПОЛЬЗУЙ ДРУГИЕ,УЧИТУЙ РЕЕСТРЫ,ИМЕННО ТАКИЕ КЛЮЧИ НИКАКИХ ДРУГИХ,НЕ ИСПОЛЬЗУЙ НА РУССКОМ ИЛИ УКРАИНСКОМ КЛЮЧИ В JSON ОТВЕТЕ!!!!!!!!!!\
                                                Состав из которого сделана вещь передай в процентном соотношении и в полном обьеме который можешь взять с этикетки если она есть\
                                                    Все результаты должны быть на украинском языке. Если на фото есть какой либо принт,фото и тд - он не может быть никак однотонным или монотонным,выбирай другой вариант\
                                                        Если нет бирки то больше всего что нет штрихкода,в таких случаях лучше всего пропускай этот результат. Все результаты которые не можешь определить передавай как None\
                                                            Если нет бирки и ты не нашел штрихкод то отправляй в результат None

                            """
        }]
        for item in image_set:

            gpt_images.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{item}"}})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        payload = {
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": gpt_images
                }
            ],
            "max_tokens": 300
        }

        while True:
            response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            if response.status_code == 429:
                print(response.text)
                time.sleep(120)
            else:
                print(response.status_code)
                result = json.loads(response.json().get('choices')[0].get('message').get('content').replace('\n', ''))
                end_result = [result.get('code'),articule,result.get('Size'),result.get('Category'),result.get('Color'),result.get('Pattern'),result.get('Gender'),result.get('Seasonality'),result.get('Style'),result.get('Country of manufacture'),result.get('Brand'),result.get('Collection'),result.get('Сompound')]
                result_list.append(end_result)
                break
        x=x+1
        if x%1==0:
            help_bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=f'Зроблено {x}/{len(image_files)}')
        time.sleep(10)
    return result_list



async def main() -> None:
    await dp.start_polling(bot)

if __name__ == "__main__":
    bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
    dp['bot'] = bot
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
