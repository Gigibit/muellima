# Personal School 🎓

Una scuola AI personalizzata costruita con Django e OpenAI Realtime API.
Inserisci qualsiasi materia, genera un corso completo e segui lezioni vocali 
interattive con un professore AI.

## Requisiti

- Python 3.10+
- Una chiave API OpenAI valida
- Browser con supporto WebRTC (Chrome, Firefox, Edge — raccomandato Chrome)

## Setup

```bash
# 1. Clona o scarica il progetto
cd personal_school

# 2. Crea un virtual environment
python -m venv venv

# 3. Attiva il virtual environment
# Su macOS/Linux:
source venv/bin/activate
# Su Windows:
venv\Scripts\activate

# 4. Installa le dipendenze
pip install -r requirements.txt

# 5. Configura le variabili d'ambiente
cp .env.example .env
# Edita .env e inserisci la tua OPENAI_API_KEY

# 6. Crea le migrazioni e applica
python manage.py makemigrations
python manage.py migrate

# 7. Avvia il server
python manage.py runserver

