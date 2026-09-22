"""Contract test verifying event consumer uniqueness in composition root.

Ensures that each consumer in ``ALL_CONSUMERS`` in ``app.bootstrap`` appears
exactly once, both by class type and by consumer group name. This prevents duplicate
consumer registrations resulting from merge conflicts or redundant wiring.
"""

from app.bootstrap import ALL_CONSUMERS


def test_all_consumers_class_types_are_unique() -> None:
    """Assert each consumer class type in ALL_CONSUMERS appears exactly once."""
    consumer_types = [type(consumer) for consumer in ALL_CONSUMERS]
    unique_types = set(consumer_types)
    assert len(consumer_types) == len(unique_types), (
        f"Duplicate consumer types found in ALL_CONSUMERS: "
        f"{[t.__name__ for t in consumer_types if consumer_types.count(t) > 1]}"
    )


def test_all_consumers_group_names_are_unique() -> None:
    """Assert each consumer group name in ALL_CONSUMERS appears exactly once."""
    group_names = [consumer.group for consumer in ALL_CONSUMERS]
    unique_groups = set(group_names)
    assert len(group_names) == len(unique_groups), (
        f"Duplicate consumer group names found in ALL_CONSUMERS: "
        f"{[g for g in group_names if group_names.count(g) > 1]}"
    )
