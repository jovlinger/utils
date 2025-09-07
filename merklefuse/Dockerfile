FROM python:3.13-alpine

# Install FUSE and development tools
RUN apk add --no-cache \
    fuse3 \
    fuse3-dev \
    gcc \
    musl-dev \
    linux-headers

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create data directory
RUN mkdir -p data

# Set up for development
CMD ["/bin/sh"]
