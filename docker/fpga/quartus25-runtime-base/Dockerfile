FROM ubuntu:24.04

# Vendor-free, original open-source runtime foundation only.
# The Quartus toolchain must be mounted by an independently admitted trusted
# actor; never COPY vendor archives or authenticated Google Drive tokens here.
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends \
         bash ca-certificates python3 libglib2.0-0 libx11-6 libfreetype6 libfontconfig1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 builder \
    && useradd -m -u 10001 -g builder builder
USER builder
WORKDIR /workspace
CMD ["python3", "--version"]
