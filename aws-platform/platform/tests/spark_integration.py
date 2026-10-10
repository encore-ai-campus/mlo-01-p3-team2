# Spark 커넥터 연동 확인 (구축 후 수동 실행). Spark 노드에서 spark-submit으로 제출한다.
#   Kafka 토픽을 읽고 -> MySQL(JDBC)과 MongoDB에 쓴 뒤 다시 읽어 건수를 비교한다.
# 값은 환경변수로 받는다: KAFKA_BOOTSTRAP, KAFKA_TOPIC, EXPECTED_COUNT, MYSQL_HOST, MONGO_HOSTS, DEV_USER_PASSWORD_MYSQL, DEV_USER_PASSWORD_MONGO
import os
from urllib.parse import quote
from pyspark.sql import SparkSession

env = os.environ
mysql_pw = env["DEV_USER_PASSWORD_MYSQL"]
mongo_uri = "mongodb://dev:{}@{}/?replicaSet=infra&authSource=admin".format(quote(env["DEV_USER_PASSWORD_MONGO"], safe=""), env["MONGO_HOSTS"])

spark = (SparkSession.builder.appName("infra-integration")
         .config("spark.mongodb.write.connection.uri", mongo_uri)
         .config("spark.mongodb.read.connection.uri", mongo_uri)
         .getOrCreate())

df = (spark.read.format("kafka")
      .option("kafka.bootstrap.servers", env["KAFKA_BOOTSTRAP"])
      .option("subscribe", env["KAFKA_TOPIC"])
      .option("startingOffsets", "earliest").option("endingOffsets", "latest")
      .load().selectExpr("CAST(key AS STRING) AS k", "CAST(value AS STRING) AS v"))
expected = int(env["EXPECTED_COUNT"])
n = df.count()
assert n == expected, "Kafka에서 {}건을 읽었다 (기대 {})".format(n, expected)

jdbc = {"url": "jdbc:mysql://{}:3306/p8db".format(env["MYSQL_HOST"]), "dbtable": "msgs", "user": "dev",
        "password": mysql_pw, "driver": "com.mysql.cj.jdbc.Driver"}
df.write.format("jdbc").options(**jdbc).mode("overwrite").save()
assert spark.read.format("jdbc").options(**jdbc).load().count() == n, "MySQL에서 읽은 건수가 다르다"

df.write.format("mongodb").option("database", "p8db").option("collection", "msgs").mode("overwrite").save()
assert spark.read.format("mongodb").option("database", "p8db").option("collection", "msgs").load().count() == n, "MongoDB에서 읽은 건수가 다르다"

print("INFRA_INTEGRATION_OK", n)
spark.stop()
