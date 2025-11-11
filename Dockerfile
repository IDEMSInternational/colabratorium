FROM python:3.12-slim

WORKDIR /app

# Copy only requirements first for better Docker layer caching
COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY collaboratorium/ /app/collaboratorium/

EXPOSE 8050

ENTRYPOINT ["python", "./collaboratorium/main.py"]
