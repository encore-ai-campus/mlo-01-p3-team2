FROM apache/spark:4.2.0
USER root
COPY requirements.txt /opt/pipeline/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /opt/pipeline/requirements.txt
COPY runtime_lock.json prepare_jars.py /opt/pipeline/
COPY jars/ /opt/pipeline/jars/
RUN python3 /opt/pipeline/prepare_jars.py --directory /opt/pipeline/jars --verify-only
RUN python3 - <<'PY'
import json, shutil
from pathlib import Path
lock=json.loads(Path('/opt/pipeline/runtime_lock.json').read_text())
for item in lock['spark_connector_jars']:
    artifact=item['path'].split('/')[-3]
    for old in Path('/opt/spark/jars').glob(artifact+'-*.jar'):
        old.unlink()
    shutil.copy2(Path('/opt/pipeline/jars')/Path(item['path']).name, '/opt/spark/jars')
PY
ENV PYTHONPATH=/opt/pipeline/srcs/spark:/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.9-src.zip
ENV PYSPARK_PYTHON=python3
COPY spark_pipeline/ /opt/pipeline/srcs/spark/spark_pipeline/
COPY contracts/ /opt/pipeline/srcs/spark/contracts/
COPY migrations/ /opt/pipeline/srcs/spark/migrations/
COPY stream.py migrate.py build_contracts.py runtime_probe.py .env.example /opt/pipeline/srcs/spark/
WORKDIR /opt/pipeline/srcs/spark
USER 185
