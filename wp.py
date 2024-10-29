import os
import requests
from bs4 import BeautifulSoup
import re
from fpdf import FPDF
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from datetime import datetime, date
import threading
import json
from flask import Flask

# Inisialisasi aplikasi Flask
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

# Fungsi untuk membersihkan dan memformat teks
def clean_text(text):
    text = re.sub(r'<p.*?>', '\n', text)
    text = re.sub(r'\xa0', '', text)
    return text

def clean_filename(title):
    title = re.sub(r'[^\x20-\x7E]', '', title)
    for i in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '^']:
        if i in title:
            title = title.replace(i, '')
    return title.lstrip('.')

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
def log_usage_to_channel(user_id):
    message = f"User ID: {user_id} telah menggunakan bot."
    updater.bot.send_message(chat_id=-1002285439982, text=message)

# Fungsi untuk mengunduh gambar
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

# Mengekstrak cerita Wattpad
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

# Memeriksa apakah URL valid
def is_valid_url(url):
    return re.match(r'^(http://|https://)', url) is not None

# Fungsi untuk membuat PDF
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
        page_height = pdf.get_page_height()
        page_center = page_height / 2

        pdf.set_y(page_center - 50) 
        pdf.set_font("Arial", 'B', 20)
        pdf.cell(0, 10, clean_filename(story_title), ln=True, align='C')
        
        pdf.ln(5)
        pdf.set_font("Arial", size=14)
        pdf.cell(0, 10, f"Penulis: {author_name}", ln=True, align='C')
        pdf.cell(0, 10, f"Tahun Terbit: {datetime.now().year}", ln=True, align='C')  
        pdf.cell(0, 10, f"Tanggal Cetak: {datetime.now().strftime('%d %B %Y')}", ln=True, align='C')  
        pdf.ln(10)

        pdf.set_font("Arial", 'B', 18)
        pdf.cell(0, 10, "Daftar Bab", ln=True, align='C')
        pdf.set_font("Arial", size=15)
        for chapter in chapters:
            pdf.cell(0, 10, chapter[0], ln=True, align='C')
        pdf.ln(10)
        pdf.set_font("Arial", size=13)
        pdf.cell(0, 10, "Dibuat oleh: Wattpad To Pdf Bot", ln=True, align='C')

        for page_num, (title, content) in enumerate(story_content, start=1):
            pdf.add_page()
            pdf.set_font("Arial", 'B', 25)
            pdf.multi_cell(0, 10, clean_filename(title), align='C')
            pdf.ln(5)
            pdf.set_font("Arial", 'I', 15)
            pdf.cell(0, 10, f"Oleh {author_name}", ln=True, align='C')
            pdf.ln(10)

            cleaned_content = re.sub(r'<[^>]+>', '', content)
            formatted_content = cleaned_content.split('\n')

            pdf.set_font("Arial", size=20)
            for paragraph in formatted_content:
                if paragraph.strip():
                    pdf.multi_cell(0, 10, paragraph, align='L')
                    pdf.ln(5)

            pdf.set_y(-25)
            pdf.set_font("Arial", size=15)
            pdf.cell(0, 10, story_title, ln=False, align='L')
            pdf.set_x(pdf.w - 15)
            pdf.cell(0, 10, f"Wattpad To Pdf | {page_num}", ln=True, align='R')

        pdf.output(pdf_filename)    

    except Exception as e:
        print(f"Error creating PDF: {e}")

# Fungsi untuk menangani pesan
def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    initialize_user(user_id)
    reset_usage()

    user_data = load_user_data()
    user_info = user_data["users"][str(user_id)]

    if not is_premium_user(user_id) and user_info["usage_count"] >= 3:
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

        log_usage_to_channel(user_id)

        # Memanggil fungsi create_pdf untuk menghasilkan file PDF
        pdf_filename = f"{clean_filename(story_title)} by {clean_filename(author_name)} (WattpadToPdfbot).pdf"
        create_pdf(chapters, story_content, image_url, author_name, story_title, pdf_filename)

        if os.path.exists(pdf_filename):
            with open(pdf_filename, 'rb') as pdf:
                update.message.reply_document(pdf)
        else:
            update.message.reply_text('File PDF tidak dapat dibuat.')

        context.bot.delete_message(chat_id=update.message.chat_id, message_id=message.message_id)

# Fungsi untuk menangani perintah /start
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Selamat datang di Wattpad To PDF Bot! Kirimkan URL cerita Wattpad yang ingin Anda konversi ke PDF."
    )

# Fungsi untuk menambahkan anggota premium
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
    if user_id not in [1910497806, 5833893519, 5166575484, 6172467461]:  # Memeriksa apakah pengguna adalah developer
        update.message.reply_text('Anda tidak memiliki izin untuk mengakses perintah ini.')
        return

    command = context.args[0] if context.args else None
    target_user_id = int(context.args[1]) if len(context.args) > 1 else None

    if command == "addpremium" and target_user_id:
        add_premium_member(target_user_id)
        update.message.reply_text(f'User ID {target_user_id} telah ditambahkan sebagai premium.')
    elif command == "delpremium" and target_user_id:
        remove_premium_member(target_user_id)
        update.message.reply_text(f'User ID {target_user_id} telah dihapus dari premium.')
    else:
        update.message.reply_text('Perintah tidak dikenali atau parameter tidak valid.')

# Fungsi untuk menjalankan aplikasi Flask
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.get_json()
    print(update)  # Log the received update for debugging
    if "message" in update and "text" in update["message"]:
        handle_message(update)
    return '', 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8000)))

# Fungsi utama
def main():
   
    updater = Updater("8079725112:AAHnpBTTWz_fpJPhW8Pv3vEcZHnlOQhXYlg")  # Ganti dengan token bot Anda
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_admin_commands))

    # Menjalankan bot
    updater.start_polling()

    # Jalankan Flask app di thread terpisah
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()

if __name__ == '__main__':
    main()
