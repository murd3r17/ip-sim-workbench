import json

from sqlalchemy import create_engine, text

from scripts.verify_live_migration import capture_database


def test_original_column_comparison_detects_changes_after_new_columns_are_added():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE business (id INTEGER PRIMARY KEY, data TEXT)'))
        connection.execute(text('INSERT INTO business VALUES (1, :value)'), {'value': 'private-fixture-content'})
    before = capture_database(engine)
    projection = {name: value['columns'] for name, value in before['tables'].items()}
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE business ADD COLUMN nullable_field TEXT'))
    assert capture_database(engine, projection) == before
    with engine.begin() as connection:
        connection.execute(text('UPDATE business SET data=:value'), {'value': 'changed-private-fixture'})
    assert capture_database(engine, projection) != before
    assert 'private-fixture-content' not in json.dumps(before)
    engine.dispose()


def test_row_order_does_not_hide_or_create_content_differences():
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE business (value TEXT)'))
        connection.execute(text("INSERT INTO business VALUES ('a'), ('b'), ('a')"))
    before = capture_database(engine)
    with engine.begin() as connection:
        connection.execute(text('DELETE FROM business'))
        connection.execute(text("INSERT INTO business VALUES ('b'), ('a'), ('a')"))
    assert capture_database(engine) == before
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO business VALUES ('a')"))
    assert capture_database(engine) != before
    engine.dispose()
