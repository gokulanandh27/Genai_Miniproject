# Enterprise AI Scraper (Deep Map-Reduce & RAG)

A powerful, resilient web scraping system that uses Playwright for dynamic content and Gemini for intelligent data extraction.

## 🚀 Setup Instructions for a New System

If you are setting this up on a new computer, follow these steps:

### 1. Clone the Repository
```bash
git clone https://github.com/gokulanandh27/Genai_Miniproject.git
cd Genai_Miniproject
git checkout dev
```

### 2. Create a Virtual Environment
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers
This is required for the dynamic scraping to work:
```bash
playwright install chromium
```

### 5. Configure Environment Variables
Since the `.env` file is ignored by Git for security, you must recreate it:
1. Create a file named `.env` in the root directory.
2. Add your Gemini API key:
   ```env
   GOOGLE_API_KEY=your_actual_api_key_here
   ```

### 6. Run the Application
```bash
python run.py
```
Then open your browser to `http://127.0.0.1:8000`.

## 🛠 Features
- **Exhaustive Map-Reduce Extraction**: Scrapes entire sites and extracts every single item matching your prompt.
- **Dynamic Content Support**: Uses Playwright to handle React, Vue, and infinite scroll websites.
- **Stealth Mode**: Built-in anti-bot detection bypass.
- **Custom Schema**: Interpret any natural language prompt into structured JSON.
