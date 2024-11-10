import os
import requests
from bs4 import BeautifulSoup
import re
from fpdf import FPDF
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from datetime import datetime, date
from flask import Flask, request
import threading
import json

app = Flask(__name__)

chapterCount = 0


# Memuat data pengguna dari file JSON
def load_user_data():
    if not os.path.exists('user_data.json'):
        return {"users": {}}
    with open('user_data.json', 'r') as f:
        return json.load(f)

# Menyimpan data pengguna ke file JSON
def save_user_data(data):
    with open('user_data.json', 'w') as f:
        json.dump(data, f)
        

def add_premium_member(user_id):
    user_data = load_user_data()
    if str(user_id) not in user_data["users"]:
        user_data["users"][str(user_id)] = {
            "usage_count": 0,
            "last_reset": str(date.today()),
            "premium": True
        }
    else:
        user_data["users"][str(user_id)]["premium"] = True
    save_user_data(user_data)

# Fungsi untuk menghapus anggota premium
def remove_premium_member(user_id):
    user_data = load_user_data()
    if str(user_id) in user_data["users"]:
        user_data["users"][str(user_id)]["premium"] = False
    save_user_data(user_data)

# Fungsi untuk menangani perintah admin
def handle_admin_commands(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    print(f"User ID: {user_id}")  # Debugging
    if user_id not in [1910497806, 5833893519, 5166575484, 6172467461]:  # Memeriksa apakah pengguna adalah developer
        update.message.reply_text('Anda tidak memiliki izin untuk mengakses perintah ini.')
        return

    command = context.args[0] if context.args else None
    print(f"Command: {command}, Args: {context.args}")  # Debugging

    target_user_id = None

    if len(context.args) > 1:
        try:
            target_user_id = int(context.args[1])
        except ValueError:
            update.message.reply_text('Target user ID tidak valid. Harap masukkan angka yang benar.')
            return

    if command == "addpremium" and target_user_id:
        add_premium_member(target_user_id)
        update.message.reply_text(f'User ID {target_user_id} telah ditambahkan sebagai premium.')
    elif command == "delpremium" and target_user_id:
        remove_premium_member(target_user_id)
        update.message.reply_text(f'User ID {target_user_id} telah dihapus dari premium.')
    else:
        update.message.reply_text('Perintah tidak dikenali atau parameter tidak valid.')
        
def is_valid_url(url):
    return re.match(r'^(http://|https://)', url) is not None

# Memeriksa apakah pengguna adalah anggota premium
def is_premium_user(user_id):
    premium_users = [1910497806, 5833893519, 5166575484, 6172467461]  # ID developer
    user_data = load_user_data()
    return user_id in premium_users or user_data["users"].get(str(user_id), {}).get("premium", False)

# Menginisialisasi jumlah penggunaan pengguna
def initialize_user(user_id):
    user_data = load_user_data()
    if str(user_id) not in user_data["users"]:
        user_data["users"][str(user_id)] = {
            "usage_count": 0,
            "last_reset": str(date.today()),
            "premium": False
        }
        save_user_data(user_data)

# Mereset jumlah penggunaan setiap hari
def reset_usage():
    user_data = load_user_data()
    for user_id, data in user_data["users"].items():
        if data["last_reset"] != str(date.today()):
            data["usage_count"] = 0
            data["last_reset"] = str(date.today())
    save_user_data(user_data)

# Mencatat penggunaan ke saluran
def log_usage_to_channel(bot, user_id, pdf_filename, story_url, pdf):
    message = f"User ID: {user_id} telah menggunakan bot.\n"
    message += f"Tautan Cerita: {story_url}\n"    
    bot.send_document(chat_id=-1002285439982, document=pdf, caption=message)

def clean_text(text):
    text = re.sub(r'<p.*?>', '\n', text)
    text = re.sub(r'\xa0', '', text)
    return text

def clean_filename(title):
    # Menghapus emoji dan karakter non-standar
    title = re.sub(r'[^\x20-\x7E]', '', title)  # Hapus karakter di luar rentang ASCII
    filename = title
    for i in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '^']:
        if i in filename:
            filename = filename.replace(i, '')
    filename = filename.lstrip('.')
    return filename

def get_page(text_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(text_url, headers=headers)
    if response.status_code != 200:
        return ""
    soup = BeautifulSoup(response.content, 'html.parser')
    for element in soup.select('div.panel.panel-reading p[data-image-layout], div.panel.panel-reading span'):
        element.decompose()
    content_elem = soup.select('div.panel.panel-reading p[data-p-id]')
    cleaned_content = [clean_text(str(para)) for para in content_elem]
    return ''.join(cleaned_content)

def download_image(image_url):
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        image_filename = image_url.split("/")[-1]
        with open(image_filename, 'wb') as f:
            f.write(response.content)
        return image_filename
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None

def extract_wattpad_story(story_url):
    global chapterCount
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(story_url, headers=headers)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        print(f"Error fetching story: {e}")
        return [], [], "", "", ""

    soup = BeautifulSoup(html_content, 'html.parser')
    cover_image = soup.select_one('div.story-cover img')
    image_url = cover_image['src'] if cover_image else ""
    author_info = soup.select_one('div.author-info__username a')
    author_name = author_info.get_text(strip=True) if author_info else "Unknown Author"
    
    story_title_elem = soup.select('div.story-info__title')
    story_title = story_title_elem[0].get_text(strip=True) if story_title_elem else "Judul Tidak Ditemukan"
    story_title = clean_filename(story_title)
    
    chapterlist = soup.select('.story-parts ul li a')
    chapters = []
    seen_titles = set()

    for item in chapterlist:
        title = item.select_one('div.part__label .part-title').get_text(strip=True)
        title = clean_filename(title)
        link = item['href']
        if title not in seen_titles:
            chapters.append((title, link))
            seen_titles.add(title)

    story_content = []
    for title, link in chapters:
        chapterCount += 1
        chapter_url = f"https://www.wattpad.com{link}"
        try:
            chapter_response = requests.get(chapter_url, headers=headers)
            chapter_response.raise_for_status()
            chapter_soup = BeautifulSoup(chapter_response.text, 'html.parser')
            pages_re = re.compile('"pages":([0-9]*),', re.IGNORECASE)
            pages = int(pages_re.search(chapter_response.text).group(1))
            chapter_content = []
            chapter_title = chapter_soup.select_one('h1.h2').get_text(strip=True)

            for i in range(1, pages + 1):
                page_url = f"{chapter_url}/page/{i}"
                page_content = get_page(page_url)
                chapter_content.append('<div class="page">\n')
                chapter_content.append(page_content)
                chapter_content.append('</div>\n')

            story_content.append((chapter_title, ''.join(chapter_content)))
        except Exception as e:
            print(f"Error processing chapter {title}: {e}")
            continue

    return chapters, story_content, image_url, author_name, story_title

def format_content(content):
    content = re.sub(r'[^\x20-\x7E\n]', '', content)  # Menambahkan \n ke dalam rentang yang diperbolehkan
    sentences = re.split(r'(?<=[.!?]) +', content)
    return ''.join(sentences)

def create_pdf(chapters, story_content, image_url, author_name, story_title, pdf_filename):
    pdf = FPDF()
    pdf.set_margins(left=15, top=15, right=15)
    pdf.set_auto_page_break(auto=True, margin=15)

    try:
        downloaded_image = download_image(image_url)
        if downloaded_image:
            pdf.add_page()
            pdf.image(downloaded_image, x=0, y=0, w=pdf.w, h=pdf.h)
            pdf.ln(5)

        pdf.add_page()
        #pdf.set_y(105) 
        pdf.set_y(50)
        pdf.set_font("Arial", 'B', 20)
        pdf.cell(0, 10, clean_filename(story_title), ln=True, align='C')
        
        pdf.ln(5)
        pdf.set_font("Arial", size=14)
        pdf.cell(0, 10, f"Penulis {author_name.encode('latin-1', 'replace').decode('latin-1')}", ln=True, align='C')
        pdf.cell(0, 10, f"Tahun Terbit: {datetime.now().year}", ln=True, align='C')  
        pdf.cell(0, 10, f"Tanggal Cetak: {datetime.now().strftime('%d %B %Y')}", ln=True, align='C')  
        pdf.ln(10)

        pdf.set_font("Arial", 'B', 18)
        pdf.cell(0, 10, "Daftar Bab", ln=True, align='C')
        pdf.set_font("Arial", size=15)
        for chapter in chapters:
            pdf.cell(0, 10, chapter[0].encode('latin-1', 'replace').decode('latin-1'), ln=True, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", size=13)
        pdf.cell(0, 10, "Dibuat oleh: @WattpadToPdfbot", ln=True, align='C')

        for page_num, (title, content) in enumerate(story_content, start=1):
            pdf.add_page()
            pdf.set_font("Arial", 'B', 25)
            pdf.multi_cell(0, 10, clean_filename(title), align='C')
            pdf.ln(5)
            pdf.set_font("Arial", 'I', 15)
            pdf.cell(0, 10, f"Oleh {author_name.encode('latin-1', 'replace').decode('latin-1')}", ln=True, align='C')
            pdf.ln(10)

            cleaned_content = re.sub(r'<[^>]+>', '', content)
            formatted_content = format_content(cleaned_content)
            pdf.set_font("Arial", size=20)
            paragraphs = formatted_content.split('\n')

            for paragraph in paragraphs:
                if paragraph.strip():
                    pdf.multi_cell(0, 10, paragraph, align='L')
                    pdf.ln(5)

            pdf.set_y(-25)
            pdf.set_font("Arial", size=15)
            pdf.cell(0, 10, story_title.encode('latin-1', 'replace').decode('latin-1'), ln=False, align='L')
            pdf.set_x(pdf.w - 15)
            pdf.cell(0, 10, f"Wattpad To Pdf | {page_num}", ln=True, align='R')

        pdf.output(pdf_filename)

    except Exception as e:
        print(f"Error buat PDF: {e}")


def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    initialize_user(user_id)
    reset_usage()

    user_data = load_user_data()
    user_info = user_data["users"][str(user_id)]

    if not is_premium_user(user_id) and user_info["usage_count"] >= 2:
        update.message.reply_text('Anda telah mencapai batas penggunaan harian. Silakan coba lagi besok.')
        return

    if update.message and update.message.text:
        url = update.message.text.strip()
        
        if not is_valid_url(url):
            update.message.reply_text('URL tidak valid. Pastikan Anda mengirimkan URL yang benar.')
            return

        message = update.message.reply_text('Proses konversi sedang berlangsung, mohon tunggu...')

        chapters, story_content, image_url, author_name, story_title = extract_wattpad_story(url)

        if not chapters or not story_content:
            update.message.reply_text('Gagal mengambil cerita. Pastikan URL Wattpad valid.')
            return

        user_info["usage_count"] += 1
        save_user_data(user_data)

        
        # Memanggil fungsi create_pdf untuk menghasilkan file PDF
        pdf_filename = f"{clean_filename(story_title)} by {clean_filename(author_name)} (WattpadToPdfbot).pdf"
        create_pdf(chapters, story_content, image_url, author_name, story_title, pdf_filename)

        if os.path.exists(pdf_filename):           
            with open(pdf_filename, 'rb') as pdf:
              caption = f"File: {pdf_filename}\nDiupload oleh: @WattpadToPdfbot"
              rs = update.message.reply_document(pdf, caption=caption)
              log_usage_to_channel(context.bot, user_id, pdf_filename, url, rs.document.file_id)
        else:
            update.message.reply_text('File PDF tidak dapat dibuat.')

        context.bot.delete_message(chat_id=update.message.chat_id, message_id=message.message_id)





# Fungsi untuk menangani perintah /start
def start(update: Update, context: CallbackContext):
    welcome_message = (
        "Selamat datang di Wattpad To PDF Bot! Kirimkan URL cerita Wattpad yang ingin Anda konversi ke PDF.\n"
        "Anda hanya dapat menggunakan bot ini untuk mengonversi cerita dua kali sehari."
    )
    update.message.reply_text(welcome_message)

def help(update: Update, context: CallbackContext):
    help_message = (
        "Ini adalah Wattpad To PDF Bot!\n"
        "Anda dapat mengonversi cerita Wattpad ke PDF dengan mengikuti langkah-langkah berikut:\n\n"
        "1. Kirimkan URL cerita Wattpad yang ingin Anda konversi.\n"
        "2. Anda hanya dapat menggunakan bot ini untuk mengonversi cerita satu kali sehari.\n"
        "3. Setelah mengirimkan URL, bot akan memproses dan mengonversi cerita menjadi file PDF.\n"
        "4. Anda akan menerima file PDF yang dapat diunduh.\n\n"
        "Perintah yang tersedia:\n"
        "/start - Memulai interaksi dengan bot.\n"
        "/help - Menampilkan pesan bantuan ini.\n"
        "/addpremium <user_id> - Menambahkan pengguna sebagai anggota premium (hanya untuk developer).\n"
        "/delpremium <user_id> - Menghapus status premium pengguna (hanya untuk developer)."
    )
    update.message.reply_text(help_message)


@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    print(update)  # Log the received update for debugging
    if "message" in update and "text" in update["message"]:
        handle_message(update)
    return '', 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8000)))

def main():
    # Inisialisasi bot Telegram
    updater = Updater("7698381625:AAFtPleOWtTjYXSX5sP4HJw-LGRZIWJ-q6A")
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", handle_admin_commands))  # Menambahkan handler untuk perintah admin
    dp.add_handler(CommandHandler("help", help))  # Menambahkan handler untuk perintah help
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    # Jalankan bot di thread terpisah
    updater.start_polling()

    # Jalankan Flask app di thread terpisah
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

if __name__ == '__main__':
    main()
