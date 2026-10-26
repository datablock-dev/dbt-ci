{#
    Macros dbt-ci runs with `dbt run-operation` to drop relations and schemas on any
    adapter. The DDL comes from the adapter's own dispatched macros (get_drop_sql,
    drop_schema), so DROP TABLE vs DROP VIEW, CASCADE and quoting are whatever that
    adapter does for dbt itself.

    Both take a list of mappings with `database` (may be null), `schema` and, for
    relations, `identifier`. Relations that do not exist are skipped, so a teardown can be
    retried safely.
#}

{% macro dbt_ci_drop_relations(relations) %}
    {% set state = namespace(dropped=false) %}
    {% for item in relations %}
        {% set relation = adapter.get_relation(
            database=item.get("database"),
            schema=item["schema"],
            identifier=item["identifier"]
        ) %}
        {% if relation is none %}
            {{ log("dbt-ci: " ~ item["schema"] ~ "." ~ item["identifier"] ~ " does not exist, skipping", info=true) }}
        {% else %}
            {#
                run-operation never commits, and adapter.drop_relation runs without
                opening a transaction, so on transactional adapters (Postgres, DuckDB,
                Redshift) the drop would be rolled back when the connection closes. Running
                it with auto_begin and committing below is what dbt's materializations do.
            #}
            {% call statement("dbt_ci_drop_relation", auto_begin=true) %}
                {{ get_drop_sql(relation) }}
            {% endcall %}
            {{ log("dbt-ci: dropped " ~ relation.type ~ " " ~ relation, info=true) }}
            {% set state.dropped = true %}
        {% endif %}
    {% endfor %}
    {% if state.dropped %}
        {% do adapter.commit() %}
    {% endif %}
{% endmacro %}

{% macro dbt_ci_drop_schemas(schemas) %}
    {% for item in schemas %}
        {% set relation = api.Relation.create(database=item.get("database"), schema=item["schema"]) %}
        {# adapter.drop_schema commits on its own #}
        {% do adapter.drop_schema(relation) %}
        {{ log("dbt-ci: dropped schema " ~ relation, info=true) }}
    {% endfor %}
{% endmacro %}
