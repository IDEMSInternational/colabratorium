FROM python:3.12-slim

WORKDIR /app

# Copy only requirements first for better Docker layer caching
COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY colabratorium/ /app/colabratorium/

EXPOSE 8050

ENTRYPOINT ["python", "./colabratorium/main.py"]
