FROM hashicorp/terraform:1.14.4@sha256:5dbdc45b411f4dd56c5b576b0ded0554859796fee2eaee9edd58dddddeac1acb AS terraform
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/runtime:/app
WORKDIR /app
COPY validation/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --from=terraform /bin/terraform /usr/local/bin/terraform
COPY validation/*.py /app/
COPY execution/*.py execution/bindings.schema.json /runtime/
COPY prompt-tests/*.py /prompt-tests/
USER 10001:10001
ENTRYPOINT ["python", "/app/worker.py"]
