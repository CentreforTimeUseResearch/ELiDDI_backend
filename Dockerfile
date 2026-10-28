FROM rockylinux/rockylinux:10

# Rocky 10's system Python is 3.12, which is the version the study server runs
RUN dnf install -y python3 python3-pip && dnf clean all

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    FLASK_APP=app

RUN python3 -m venv /opt/venv

WORKDIR /srv/eliddi
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY app app
COPY tests tests
COPY pytest.ini .

EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--debug"]
