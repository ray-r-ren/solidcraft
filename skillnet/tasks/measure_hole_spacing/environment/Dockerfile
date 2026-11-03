FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git xz-utils unzip file procps xvfb xauth ffmpeg libgl1 libglib2.0-0 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar xJ -C /usr/local --strip-components=1
RUN pip install --no-cache-dir pydantic==2.10.3 pytest==8.3.4 pyyaml==6.0.2 requests==2.32.3 pypdf==5.1.0
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DISPLAY=:99 MPLBACKEND=Agg
RUN mkdir -p /workspace/inputs /workspace/outputs /skill
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl xz-utils libvulkan1 mesa-vulkan-drivers libegl1 libgl1 libgl1-mesa-dri libgbm1 libfontconfig1 libfreetype6 fonts-dejavu-core libxkbcommon0 libx11-6 libxcursor1 libxrandr2 libxi6 libwayland-client0 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir numpy==1.26.4 trimesh==4.4.9 matplotlib==3.9.2 pillow==10.4.0 networkx==3.3 lxml==5.3.0
RUN set -e; mkdir -p /opt/solidcraft; cd /tmp; if curl -fsSL -o sc.tgz https://github.com/tangency-labs/solidcraft/releases/download/v0.30.1/solidcraft-0.30.1-linux-x86_64.tar.gz; then tar -xzf sc.tgz -C /opt/solidcraft; rm -f sc.tgz; else curl -fsSL -o sc.deb https://github.com/tangency-labs/solidcraft/releases/download/v0.30.1/solidcraft-linux-x86_64.deb && dpkg -x sc.deb /opt/solidcraft && rm -f sc.deb; fi
RUN set -e; B=$(find /opt/solidcraft -type f -name solidcraft-cli | head -n1); test -n "$B"; chmod 755 "$B"; ln -sf "$B" /usr/local/bin/solidcraft-cli
RUN mkdir -p /opt/solidcraft/licenses && find /opt/solidcraft -maxdepth 6 -type f \( -iname 'LICENSE*' -o -iname 'NOTICE*' -o -iname 'THIRD-PARTY*' \) -exec cp {} /opt/solidcraft/licenses/ \; || true
COPY files/ /task/
COPY inputs/ /task/inputs/
RUN rm -f /task/.keep /task/inputs/.keep && mkdir -p /task/outputs && useradd -m -u 1000 agent && chown -R agent /task
WORKDIR /task
