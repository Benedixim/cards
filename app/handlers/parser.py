#app/parsers/bank_parser.py
import asyncio
import re
from typing import Optional
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BankPageParser:
    """Парсер страниц банков с умной обработкой"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        self.cache = {}
    
    async def get_page_content(self, url: str, max_retries: int = 3) -> Optional[str]:
        """
        ✅ Получает контент страницы с множественными попытками
        
        Стратегия:
        1. Попытка через requests (быстро)
        2. Попытка через Playwright (для JS)
        3. Специальная обработка для разных банков
        """
        
        # Проверяем кэш
        if url in self.cache:
            print(f"💾 Используем кэш для {url}")
            return self.cache[url]
        
        # 1️⃣ Попытка 1: Быстрая загрузка через requests
        print(f"🔄 Попытка 1: requests для {url}")
        content = await self._load_with_requests(url)
        if content and len(content) > 1000:
            print(f"✅ Загружено через requests")
            self.cache[url] = content
            return content
        
        # 2️⃣ Попытка 2: Playwright для JS
        print(f"🔄 Попытка 2: Playwright для {url}")
        content = await self._load_with_playwright(url)
        if content and len(content) > 1000:
            print(f"✅ Загружено через Playwright")
            self.cache[url] = content
            return content
        
        # 3️⃣ Попытка 3: Специальная обработка по доменам
        print(f"🔄 Попытка 3: Специальная обработка для {url}")
        content = await self._load_with_special_handling(url)
        if content and len(content) > 1000:
            print(f"✅ Загружено со специальной обработкой")
            self.cache[url] = content
            return content
        
        print(f"❌ Не удалось загрузить {url}")
        return None
    
    async def _load_with_requests(self, url: str) -> Optional[str]:
        """Загрузка через requests"""
        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=10,
                verify=False,
                allow_redirects=True
            )
            
            if response.status_code == 200:
                response.encoding = 'utf-8'
                return response.text
        except Exception as e:
            print(f"  ⚠️ requests ошибка: {type(e).__name__}")
        
        return None
    
    async def _load_with_playwright(self, url: str, timeout: int = 30000) -> Optional[str]:
        """Загрузка через Playwright (для JS контента)"""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                    ]
                )
                
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent=self.headers['User-Agent']
                )
                
                page = await context.new_page()
                
                try:
                    # Ждём загрузки сети
                    await page.goto(url, wait_until='networkidle', timeout=timeout)
                    
                    # Прокручиваем для загрузки ленивого контента
                    await page.evaluate("""
                        async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 100;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    
                                    if(totalHeight >= scrollHeight){
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 100);
                            });
                        }
                    """)
                    
                    # Получаем контент
                    content = await page.content()
                    await browser.close()
                    return content
                    
                except Exception as e:
                    print(f"  ⚠️ Playwright ошибка: {type(e).__name__}")
                    await browser.close()
                    return None
                    
        except Exception as e:
            print(f"  ⚠️ Критическая ошибка Playwright: {type(e).__name__}")
            return None
    
    async def _load_with_special_handling(self, url: str) -> Optional[str]:
        """Специальная обработка для разных банков"""
        try:
            # Определяем банк по URL
            if "sberbank.by" in url or "sber" in url.lower():
                return await self._load_sberbank(url)
            elif "alfabank" in url.lower():
                return await self._load_alfabank(url)
            elif "mtbank" in url.lower():
                return await self._load_mtbank(url)
            else:
                # Стандартная загрузка с другими параметрами
                headers = self.headers.copy()
                headers['Referer'] = url.rsplit('/', 1)[0] + '/'
                
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=15,
                    verify=False,
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    response.encoding = 'utf-8'
                    return response.text
        except Exception as e:
            print(f"  ⚠️ Специальная обработка ошибка: {type(e).__name__}")
        
        return None
    
    async def _load_sberbank(self, url: str) -> Optional[str]:
        """Специальная обработка для Сбера"""
        try:
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.sber-bank.by/'
            
            response = requests.get(url, headers=headers, timeout=12, verify=False)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"  ⚠️ Sberbank ошибка: {type(e).__name__}")
        return None
    
    async def _load_alfabank(self, url: str) -> Optional[str]:
        """Специальная обработка для Альфа Банка"""
        try:
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.alfabank.by/'
            
            response = requests.get(url, headers=headers, timeout=12, verify=False)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"  ⚠️ Alfabank ошибка: {type(e).__name__}")
        return None
    
    async def _load_mtbank(self, url: str) -> Optional[str]:
        """Специальная обработка для МТБанка"""
        try:
            headers = self.headers.copy()
            headers['Referer'] = 'https://www.mtbank.by/'
            
            response = requests.get(url, headers=headers, timeout=12, verify=False)
            if response.status_code == 200:
                return response.text
        except Exception as e:
            print(f"  ⚠️ MTBank ошибка: {type(e).__name__}")
        return None
    
    def extract_text(self, html: str, min_length: int = 100) -> str:
        """
        ✅ Умное извлечение текста из HTML
        - Удаляет скрипты и стили
        - Сохраняет структуру
        - Очищает от лишних пробелов
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Удаляем лишние теги
            for tag in soup(['script', 'style', 'meta', 'link', 'svg', 'iframe', 
                           'noscript', 'nav', 'footer', 'button', 'form']):
                tag.decompose()
            
            # Удаляем комментарии
            for element in soup(string=lambda text: isinstance(text, str) and text.strip().startswith('<!--')):
                element.extract()
            
            # Извлекаем текст с сохранением структуры
            text = soup.get_text(separator=" ", strip=True)
            
            # Очищаем от множественных пробелов
            text = re.sub(r'\s+', ' ', text)
            
            # Ограничиваем размер (8000 символов достаточно для LLM)
            return text[:8000]
        
        except Exception as e:
            print(f"❌ Ошибка извлечения текста: {e}")
            return ""
    
    def extract_structured_data(self, html: str) -> dict:
        """
        ✅ Извлечение структурированных данных из HTML
        - Таблицы
        - Списки
        - Определения
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            data = {}
            
            # Извлекаем таблицы
            tables = soup.find_all('table')
            if tables:
                data['tables'] = []
                for table in tables[:3]:  # Первые 3 таблицы
                    rows = []
                    for tr in table.find_all('tr')[:10]:  # Первые 10 строк
                        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                        if cells:
                            rows.append(cells)
                    if rows:
                        data['tables'].append(rows)
            
            # Извлекаем списки
            lists = soup.find_all(['ul', 'ol'])
            if lists:
                data['lists'] = []
                for lst in lists[:5]:
                    items = [li.get_text(strip=True) for li in lst.find_all('li')]
                    if items:
                        data['lists'].append(items)
            
            return data
        
        except Exception as e:
            print(f"⚠️ Ошибка извлечения структурированных данных: {e}")
            return {}


# Глобальный экземпляр парсера
parser = BankPageParser()


async def get_page_content(url: str) -> Optional[str]:
    return await parser.get_page_content(url)


async def extract_page_text(url: str) -> str:
    content = await get_page_content(url)
    if content:
        return parser.extract_text(content)
    return ""