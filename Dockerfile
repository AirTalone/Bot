FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py qr_generator.py generate_once.py ./
COPY exchange ./exchange

RUN mkdir -p /app/data

ENV DATABASE_PATH=/app/data/exchange.db

CMD ["python", "bot.py"]
