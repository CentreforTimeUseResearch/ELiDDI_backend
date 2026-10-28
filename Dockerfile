FROM rockylinux/rockylinux:10

# Rocky 10's own Python is 3.12, so install the pinned version with uv
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    FLASK_APP=app

RUN uv venv --python 3.15.1 /opt/venv

WORKDIR /srv/eliddi
COPY requirements.txt requirements-dev.txt ./
RUN uv pip install -r requirements-dev.txt

COPY app app
COPY tests tests
COPY pytest.ini .

EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--debug"]
