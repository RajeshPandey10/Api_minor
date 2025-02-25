FROM python:3.11-slim

# Install system dependencies and Google Chrome using modern key method
RUN apt-get update && \
    apt-get install -y wget gnupg2 curl && \
    mkdir -p /usr/share/keyrings && \
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor | tee /usr/share/keyrings/google-linux-signing-key.gpg > /dev/null && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux-signing-key.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -f /usr/bin/google-chrome && \
    ln -s /usr/bin/google-chrome-stable /usr/bin/google-chrome && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
# Copy and install Python dependencies. Use './' to refer to the current directory.
COPY ./requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire API code into the container
COPY . /app/
CMD ["python", "server1.py"]
