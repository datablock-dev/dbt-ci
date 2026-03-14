"""MySQL connector for dbt CI."""
import logging
from argparse import Namespace
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dbt_ci.connectors.sql.sql_connector import SqlConnector
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
