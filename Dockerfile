# Bookroom - self-contained image.
#
# The engine ships inside the package, so this is a plain pip install with no
# second checkout. Build from the repository root:
#
#   docker build -t bookroom .
#   docker run --rm -v "$PWD/books:/books" -v "$PWD/out:/out" \
#     -e GEMINI_API_KEY -e TYPESAFE_API_KEY bookroom extract /books/book.pdf

FROM python:3.13-slim AS build

WORKDIR /src
COPY python/ ./python/
RUN pip install --no-cache-dir "./python[all]" build

FROM python:3.13-slim

# Tesseract is only needed for scanned PDFs; the SDK degrades gracefully without it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin/bookroom /usr/local/bin/bookroom

ENV PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/out \
    TESSERACT_CMD=/usr/bin/tesseract

VOLUME ["/books", "/out"]
WORKDIR /out

# The facade for non-Python clients. Bind to loopback or put a reverse proxy
# with real authorization in front of it - it has no user authentication
# beyond its token. See SECURITY.md.
EXPOSE 8787

ENTRYPOINT ["bookroom"]
CMD ["--help"]
