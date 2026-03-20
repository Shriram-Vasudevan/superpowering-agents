FROM python:3.12-slim

WORKDIR /app

# Install system deps for Pillow + Playwright/Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev libpng-dev \
    # Chromium runtime dependencies
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libxcb1 libxkbcommon0 \
    libpango-1.0-0 libcairo2 libasound2 libx11-xcb1 libxcursor1 \
    libxi6 libxtst6 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (avoids pulling ~4GB of CUDA)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install Python deps
COPY pyproject.toml .
COPY src/__init__.py src/__init__.py
RUN pip install --no-cache-dir .

# Copy source + reference data
COPY src/ src/
COPY reference_data/ reference_data/
COPY index_data/ index_data/

# Reinstall with full source
RUN pip install --no-cache-dir .

# Pre-download CLIP model so it's baked into the image (avoids runtime download + OOM)
RUN python -c "from transformers import CLIPModel, CLIPProcessor; CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')"

# Install Playwright Chromium browser (baked in so layout_checker works at runtime)
RUN playwright install chromium

EXPOSE 8000

CMD ["python", "-m", "src.mcp_server", "--http", "--port", "8000"]
