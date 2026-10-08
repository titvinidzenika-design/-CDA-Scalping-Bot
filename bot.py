import xml.etree.ElementTree as ET

def get_crypto_news():
    """იღებს უახლეს სიახლეებს CoinTelegraph RSS-იდან სრულიად უფასოდ"""
    url = "https://cointelegraph.com/rss"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall('.//item')
            
            news_list = []
            for item in items[:5]: # იღებს ბოლო 5 სიახლეს
                title = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                if title:
                    news_list.append(f"• [{title}]({link})")
            
            return "\n\n".join(news_list)
        else:
            return "❌ სიახლეების წამოღება ვერ მოხერხდა."
    except Exception as e:
        print(f"News RSS error: {e}")
        return "❌ სიახლეების სერვერთან კავშირი ვერ დამყარდა."

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ იტვირთება უახლესი კრიპტო სიახლეები...")
    news_text = get_crypto_news()
    res = f"📰 **უახლესი გლობალური კრიპტო სიახლეები:**\n\n{news_text}"
    await update.message.reply_text(res, parse_mode="Markdown", disable_web_page_preview=True)

