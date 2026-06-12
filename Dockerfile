FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create the data directory
RUN mkdir -p /app/data

# Copy the application code
COPY . .

# Expose port
EXPOSE 8000

CMD ["python", "main.py"]