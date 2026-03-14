"""MySQL connector for dbt CI."""
import logging
from argparse import Namespace
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dbt_ci.connectors.sql.sql_connector import SqlConnector
from dbt_ci.schema import ConnectorConfig, DeleteMapNode
from dbt_ci.utilities.paths import get_profile

logger = logging.getLogger(__name__)

def mysql_client(args: Namespace) -> SqlConnector:
    """Create a SqlConnector for MySQL using credentials from dbt profiles.yml."""
    output = get_profile(args)

    if output.get("type") != "mysql":
        raise ValueError(
            f"Profile output type is '{output.get('type')}', expected 'mysql'."
        )

    url = URL.create(
        drivername="mysql+pymysql",
        username=output.get("username") or output.get("user"),
        password=output.get("password"),
        host=output.get("server", "localhost"),
        port=int(output.get("port", 3306)),
        database=output.get("database") or output.get("schema"),
    )
    engine = create_engine(url)
    return SqlConnector(engine)

def mysql_delete_strategy(delete_map: dict[str, DeleteMapNode], args: Namespace) -> None:
    """Delete strategy for MySQL connector."""
    # MySQL does not support CASCADE on DROP SCHEMA, so we need to drop tables first
    client = mysql_client(args)
    tables_to_delete: set[str] = set()
    for node_metadata in delete_map.values():
        table_id = node_metadata.get("table_id")
        if table_id:
            tables_to_delete.add(table_id)
            tables_to_delete.add(f"{table_id}__dbt_tmp")  # Also delete the dbt temporary table if it exists

    client.delete_tables(table_ids=tables_to_delete, dry_run=getattr(args, "dry_run", False))

mysql_db_connector: ConnectorConfig = {
    "client": mysql_client,
    "strategies": {
        "delete": mysql_delete_strategy,
        "migration": None
    },
    "methods": {
        "query": mysql_client.query,
        "create_datasets": mysql_client.create_datasets,
        "delete_datasets": mysql_client.delete_datasets,
        "create_tables": mysql_client.create_tables,
        "delete_tables": mysql_client.delete_tables 
    }
}

__init__ = [
    "mysql_db_connector"
]