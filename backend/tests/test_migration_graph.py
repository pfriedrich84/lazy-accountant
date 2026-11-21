from django.db.migrations.loader import MigrationLoader


def test_migration_graph_has_no_conflicting_leaves():
    loader = MigrationLoader(None)

    assert loader.detect_conflicts() == {}
    assert loader.graph.leaf_nodes("accounting") == [
        ("accounting", "0015_package_context_sources"),
    ]
