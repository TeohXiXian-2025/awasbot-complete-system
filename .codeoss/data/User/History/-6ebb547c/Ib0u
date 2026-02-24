# 1. Use the OFFICIAL Playwright image (Chrome is already built-in!)
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# 2. Set the working directory in the cloud
WORKDIR /app

# 3. Copy your requirements and install Python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the rest of your code (main.py, etc.)
COPY . .

# 5. Start the bot using Functions Framework on port 8080
CMD ["functions-framework", "--target=telegram_webhook", "--port=8080", "--host=0.0.0.0"]