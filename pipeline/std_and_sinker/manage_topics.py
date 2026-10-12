import argparse

from confluent_kafka.admin import AdminClient, NewTopic

from sinker.config import SRC, Settings
from sinker.contracts import ContractRegistry


def main():
    parser = argparse.ArgumentParser(description="Provision configured Raw and Std topics")
    parser.add_argument("--env-file", default=str(SRC / ".env"))
    parser.add_argument("--replication-factor", type=int, default=3)
    parser.add_argument("--min-insync-replicas", type=int, default=2)
    parser.add_argument("--partitions", type=int, default=3)
    args = parser.parse_args()
    if args.partitions < 1 or not 1 <= args.min_insync_replicas <= args.replication_factor:
        parser.error("Invalid partitions or replication settings")
    settings = Settings.from_env(args.env_file)
    registry = ContractRegistry(settings.contracts_dir, settings.routes_file)
    registry.validate_topics(settings.input_topics)
    topics = set(settings.input_topics)
    topics.update(registry.routes[topic]["output_topic"] for topic in settings.input_topics)
    admin = AdminClient(settings.connection_config())
    existing = set(admin.list_topics(timeout=10).topics)
    new = topics - existing
    if not new:
        print(f"Ready: {len(topics)} configured topics")
        return
    for topic, future in admin.create_topics([
        NewTopic(topic, num_partitions=args.partitions, replication_factor=args.replication_factor,
                 config={"min.insync.replicas": str(args.min_insync_replicas)})
        for topic in sorted(new)
    ]).items():
        future.result(timeout=30)
        print(f"Created {topic}")
    print(f"Ready: {len(topics)} configured topics")


if __name__ == "__main__":
    main()
