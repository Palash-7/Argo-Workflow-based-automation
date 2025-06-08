FROM ubuntu:20.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# ───── Install system packages ─────
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      curl \
    && rm -rf /var/lib/apt/lists/*

# ───── Install Python dependencies ─────
COPY requirements.txt /app/requirements.txt
WORKDIR /app
RUN pip3 install --no-cache-dir -r requirements.txt

# ───── Copy Python script ─────
COPY rack_resiliency_to_host.py /app/rack_resiliency_to_host.py

# Make sure the logs directory exists
RUN mkdir -p /app/logs

# Install kubectl for potential debugging
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x ./kubectl && \
    mv ./kubectl /usr/local/bin/kubectl

# Entrypoint: let Argo override with "command" and "args"
ENTRYPOINT ["/bin/bash", "-c"]
CMD ["bash"] 
