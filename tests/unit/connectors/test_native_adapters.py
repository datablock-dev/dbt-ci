"""Unit tests for the per-adapter native connectors.

The warehouse drivers live in optional extras and are not installed in CI, so these tests
exercise the two things that are ours: translating a dbt profile into connection arguments,
and rendering each warehouse's migration SQL.
"""
import pytest

from dbt_ci.connectors.azure.client import build_connection_string
from dbt_ci.connectors.azure.migration import plan_synapse_migration
from dbt_ci.connectors.databricks.client import (
    build_connect_kwargs as databricks_kwargs,
    normalise_host,
)
from dbt_ci.connectors.databricks.migration import plan_databricks_migration
from dbt_ci.connectors.mysql import build_connect_kwargs as mysql_kwargs
from dbt_ci.connectors.postgres import build_connect_kwargs as postgres_kwargs
from dbt_ci.connectors.redshift.client import build_connect_kwargs as redshift_kwargs
from dbt_ci.connectors.redshift.migration import plan_redshift_migration
from dbt_ci.connectors.snowflake.client import build_connect_kwargs as snowflake_kwargs
from dbt_ci.connectors.snowflake.migration import plan_snowflake_migration


class TestSnowflakeProfile:
    """Test translation of a dbt-snowflake profile."""

    def test_password_authentication(self):
        """A password profile maps straight onto the driver's arguments."""
        kwargs = snowflake_kwargs({
            "account": "acct", "user": "u", "password": "p",
            "role": "TRANSFORMER", "warehouse": "WH", "database": "DB", "schema": "SCH",
        })
        assert kwargs["account"] == "acct"
        assert kwargs["password"] == "p"
        assert kwargs["warehouse"] == "WH"
        assert kwargs["session_parameters"] == {"QUERY_TAG": "dbt-ci"}

    def test_sso_authenticator_takes_precedence_over_password(self):
        """An explicit authenticator is honoured rather than falling back to a password."""
        kwargs = snowflake_kwargs({
            "account": "acct", "user": "u", "password": "p",
            "authenticator": "externalbrowser",
        })
        assert kwargs["authenticator"] == "externalbrowser"
        assert "password" not in kwargs

    def test_mfa_authenticator_keeps_the_password(self):
        """username_password_mfa still needs the password alongside the authenticator."""
        kwargs = snowflake_kwargs({
            "account": "acct", "user": "u", "password": "p",
            "authenticator": "username_password_mfa",
        })
        assert kwargs["authenticator"] == "username_password_mfa"
        assert kwargs["password"] == "p"

    def test_key_pair_authentication(self, tmp_path):
        """A key-pair profile is loaded from disk and handed over in DER form."""
        pytest.importorskip("cryptography")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_file = tmp_path / "key.pem"
        key_file.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))

        kwargs = snowflake_kwargs({
            "account": "acct", "user": "u", "private_key_path": str(key_file),
        })
        assert isinstance(kwargs["private_key"], bytes)
        assert "password" not in kwargs

    def test_missing_account_is_rejected(self):
        """A profile without an account cannot connect anywhere."""
        with pytest.raises(ValueError, match="account"):
            snowflake_kwargs({"user": "u", "password": "p"})

    def test_missing_credentials_are_rejected(self):
        """A profile with no usable credential fails with an actionable message."""
        with pytest.raises(ValueError, match="credentials"):
            snowflake_kwargs({"account": "acct", "user": "u"})


class TestSnowflakeMigration:
    """Test Snowflake migration SQL."""

    def test_clustering_key_is_set_in_place(self):
        """Snowflake alters clustering in place, so no data is moved."""
        statements = plan_snowflake_migration(
            {"table_id": "db.sch.t", "new_config": {"cluster_by": ["a", "b"]}, "old_config": {}},
            "snowflake",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" CLUSTER BY (a, b)']

    def test_single_expression_is_accepted(self):
        """cluster_by may be a bare string rather than a list."""
        statements = plan_snowflake_migration(
            {"table_id": "db.sch.t", "new_config": {"cluster_by": "to_date(ts)"}, "old_config": {}},
            "snowflake",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" CLUSTER BY (to_date(ts))']

    def test_removing_clustering_drops_the_key(self):
        """Dropping cluster_by from the model drops it from the table."""
        statements = plan_snowflake_migration(
            {"table_id": "db.sch.t", "new_config": {}, "old_config": {"cluster_by": ["a"]}},
            "snowflake",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" DROP CLUSTERING KEY']

    def test_no_clustering_either_side_is_a_no_op(self):
        """Nothing to change means no statements, which the strategy reports as skipped."""
        assert plan_snowflake_migration(
            {"table_id": "db.sch.t", "new_config": {}, "old_config": {}}, "snowflake"
        ) == []


class TestRedshiftProfile:
    """Test translation of a dbt-redshift profile."""

    def test_database_authentication(self):
        """The default method sends host, database, user and password."""
        kwargs = redshift_kwargs({
            "host": "h", "dbname": "db", "user": "u", "password": "p", "port": 5439,
        })
        assert kwargs["database"] == "db"
        assert kwargs["password"] == "p"
        assert "iam" not in kwargs

    def test_iam_authentication_sends_no_password(self):
        """With IAM the driver fetches temporary credentials itself."""
        kwargs = redshift_kwargs({
            "host": "h", "dbname": "db", "user": "u", "method": "iam",
            "cluster_id": "my-cluster", "region": "eu-west-1",
        })
        assert kwargs["iam"] is True
        assert kwargs["db_user"] == "u"
        assert kwargs["cluster_identifier"] == "my-cluster"
        assert "password" not in kwargs

    def test_password_is_required_for_database_method(self):
        """Without IAM a password is mandatory, and the error says so."""
        with pytest.raises(ValueError, match="password"):
            redshift_kwargs({"host": "h", "dbname": "db", "user": "u"})


class TestRedshiftMigration:
    """Test Redshift migration SQL."""

    def test_sortkey_and_diststyle_change_together(self):
        """Both keys are altered in place, distribution first."""
        statements = plan_redshift_migration(
            {
                "table_id": "db.sch.t",
                "name": "t",
                "new_config": {"sort": ["a", "b"], "dist": "customer_id"},
                "old_config": {"sort": ["a"], "dist": "even"},
            },
            "redshift",
        )
        assert statements == [
            'ALTER TABLE "db"."sch"."t" ALTER DISTSTYLE KEY DISTKEY "customer_id"',
            'ALTER TABLE "db"."sch"."t" ALTER SORTKEY ("a", "b")',
        ]

    def test_distribution_style_keyword(self):
        """A dist naming a style renders as that style, not as a column."""
        statements = plan_redshift_migration(
            {"table_id": "db.sch.t", "name": "t", "new_config": {"dist": "all"}, "old_config": {"dist": "even"}},
            "redshift",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" ALTER DISTSTYLE ALL']

    def test_auto_sort_type(self):
        """sort_type auto hands the decision back to Redshift."""
        statements = plan_redshift_migration(
            {
                "table_id": "db.sch.t", "name": "t",
                "new_config": {"sort": ["a"], "sort_type": "auto"},
                "old_config": {"sort": ["b"], "sort_type": "compound"},
            },
            "redshift",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" ALTER SORTKEY AUTO']

    def test_removing_sort_clears_the_key(self):
        """Dropping sort from the model clears the table's sort key."""
        statements = plan_redshift_migration(
            {"table_id": "db.sch.t", "name": "t", "new_config": {}, "old_config": {"sort": ["a"]}},
            "redshift",
        )
        assert statements == ['ALTER TABLE "db"."sch"."t" ALTER SORTKEY NONE']

    def test_interleaved_sort_is_skipped_not_silently_compounded(self):
        """ALTER SORTKEY only makes compound keys, so an interleaved request is refused."""
        statements = plan_redshift_migration(
            {
                "table_id": "db.sch.t", "name": "t",
                "new_config": {"sort": ["a"], "sort_type": "interleaved"},
                "old_config": {"sort": ["b"], "sort_type": "interleaved"},
            },
            "redshift",
        )
        assert statements == []


class TestDatabricksProfile:
    """Test translation of a dbt-databricks profile."""

    def test_personal_access_token(self):
        """A token profile becomes an access_token argument."""
        kwargs = databricks_kwargs({
            "host": "https://adb-123.azuredatabricks.net/", "http_path": "/sql/1.0/x",
            "token": "dapi123", "catalog": "main", "schema": "sch",
        })
        assert kwargs["server_hostname"] == "adb-123.azuredatabricks.net"
        assert kwargs["access_token"] == "dapi123"
        assert kwargs["catalog"] == "main"

    def test_oauth_service_principal_uses_a_credentials_provider(self):
        """client_id/client_secret authenticate via OAuth rather than a token."""
        kwargs = databricks_kwargs({
            "host": "adb-123.azuredatabricks.net", "http_path": "/sql/1.0/x",
            "client_id": "id", "client_secret": "secret",
        })
        assert callable(kwargs["credentials_provider"])
        assert "access_token" not in kwargs

    def test_missing_credentials_are_rejected(self):
        """Neither a token nor a service principal means no way to authenticate."""
        with pytest.raises(ValueError, match="credentials"):
            databricks_kwargs({"host": "h", "http_path": "/sql/1.0/x"})

    def test_missing_http_path_is_rejected(self):
        """A Databricks target is unreachable without its warehouse path."""
        with pytest.raises(ValueError, match="http_path"):
            databricks_kwargs({"host": "h", "token": "t"})

    @pytest.mark.parametrize("host,expected", [
        ("https://h/", "h"),
        ("http://h", "h"),
        ("h", "h"),
    ])
    def test_host_normalisation(self, host, expected):
        """The driver wants a bare hostname whatever the profile spells."""
        assert normalise_host(host) == expected


class TestDatabricksMigration:
    """Test Databricks migration SQL."""

    def test_liquid_clustering_is_altered_in_place(self):
        """Liquid clustering changes without rewriting the table."""
        statements = plan_databricks_migration(
            {
                "table_id": "cat.sch.t",
                "new_config": {"liquid_clustered_by": ["a"]},
                "old_config": {"liquid_clustered_by": ["b"]},
            },
            "databricks",
        )
        assert statements == ["ALTER TABLE `cat`.`sch`.`t` CLUSTER BY (`a`)"]

    def test_partition_change_rewrites_through_a_staging_table(self):
        """Hive-style partitioning is fixed at creation, so the rows are rewritten."""
        statements = plan_databricks_migration(
            {
                "table_id": "cat.sch.t",
                "new_config": {"partition_by": ["day"]},
                "old_config": {"partition_by": ["month"]},
            },
            "databricks",
        )
        assert statements == [
            "CREATE OR REPLACE TABLE `cat`.`sch`.`t__dbt_ci_migration` PARTITIONED BY (`day`) "
            "AS SELECT * FROM `cat`.`sch`.`t`",
            "DROP TABLE IF EXISTS `cat`.`sch`.`t`",
            "ALTER TABLE `cat`.`sch`.`t__dbt_ci_migration` RENAME TO `cat`.`sch`.`t`",
        ]

    def test_bucketing_is_included_in_the_rewrite(self):
        """clustered_by plus buckets becomes a CLUSTERED BY ... INTO n BUCKETS clause."""
        statements = plan_databricks_migration(
            {
                "table_id": "cat.sch.t",
                "new_config": {"clustered_by": ["id"], "buckets": 8},
                "old_config": {},
            },
            "databricks",
        )
        assert "CLUSTERED BY (`id`) INTO 8 BUCKETS" in statements[0]


class TestAzureProfile:
    """Test translation of a dbt-sqlserver / synapse / fabric profile."""

    def test_sql_authentication(self):
        """SQL auth puts the credentials in UID/PWD."""
        connection_string = build_connection_string({
            "server": "srv.database.windows.net", "port": 1433, "database": "db",
            "user": "u", "password": "p",
        })
        assert "SERVER=srv.database.windows.net,1433" in connection_string
        assert "DATABASE=db" in connection_string
        assert "UID=u" in connection_string and "PWD=p" in connection_string
        assert "Encrypt=yes" in connection_string

    def test_service_principal_authentication(self):
        """A service principal travels in the same fields under an AAD method."""
        connection_string = build_connection_string({
            "server": "srv", "database": "db",
            "authentication": "ActiveDirectoryServicePrincipal",
            "client_id": "cid", "client_secret": "csecret",
        })
        assert "Authentication=ActiveDirectoryServicePrincipal" in connection_string
        assert "UID=cid" in connection_string and "PWD=csecret" in connection_string

    def test_msi_authentication_carries_no_secret(self):
        """Managed identity needs no credential of its own."""
        connection_string = build_connection_string({
            "server": "srv", "database": "db", "authentication": "ActiveDirectoryMsi",
        })
        assert "Authentication=ActiveDirectoryMsi" in connection_string
        assert "PWD=" not in connection_string

    def test_trust_cert_and_encrypt_are_honoured(self):
        """Explicit profile values win over the driver defaults."""
        connection_string = build_connection_string({
            "server": "srv", "database": "db", "user": "u", "password": "p",
            "encrypt": False, "trust_cert": True,
        })
        assert "Encrypt=no" in connection_string
        assert "TrustServerCertificate=yes" in connection_string

    def test_sql_authentication_requires_credentials(self):
        """SQL auth without a user or password fails before connecting."""
        with pytest.raises(ValueError, match="user"):
            build_connection_string({"server": "srv", "database": "db"})


class TestSynapseMigration:
    """Test Synapse migration SQL."""

    def test_distribution_change_rewrites_and_renames(self):
        """Distribution is fixed at creation, so the rows move through a staging table."""
        statements = plan_synapse_migration(
            {
                "table_id": "db.sch.t",
                "new_config": {"dist": "HASH(customer_id)", "index": "CLUSTERED COLUMNSTORE INDEX"},
                "old_config": {"dist": "ROUND_ROBIN"},
            },
            "synapse",
        )
        assert statements == [
            "CREATE TABLE [db].[sch].[t__dbt_ci_migration] "
            "WITH (DISTRIBUTION = HASH(customer_id), CLUSTERED COLUMNSTORE INDEX) "
            "AS SELECT * FROM [db].[sch].[t]",
            "DROP TABLE [db].[sch].[t]",
            "RENAME OBJECT [db].[sch].[t__dbt_ci_migration] TO [t]",
        ]

    def test_defaults_are_applied_when_config_is_partial(self):
        """A dist change with no index config keeps Synapse's default index."""
        statements = plan_synapse_migration(
            {"table_id": "db.sch.t", "new_config": {"dist": "REPLICATE"}, "old_config": {}},
            "synapse",
        )
        assert "DISTRIBUTION = REPLICATE, CLUSTERED COLUMNSTORE INDEX" in statements[0]


class TestPostgresProfile:
    """Test translation of a dbt-postgres profile."""

    def test_basic_connection(self):
        """Host, database and credentials map onto psycopg2's arguments."""
        kwargs = postgres_kwargs({
            "host": "h", "dbname": "db", "user": "u", "password": "p", "port": 5432,
        })
        assert kwargs["dbname"] == "db"
        assert kwargs["user"] == "u"

    def test_search_path_and_role_become_connection_options(self):
        """dbt applies these per connection, so the drops resolve the same relations."""
        kwargs = postgres_kwargs({
            "host": "h", "dbname": "db", "user": "u", "password": "p",
            "search_path": "analytics", "role": "transformer",
        })
        assert kwargs["options"] == "-c search_path=analytics -c role=transformer"

    def test_missing_database_is_rejected(self):
        """A Postgres target needs a database name."""
        with pytest.raises(ValueError, match="dbname"):
            postgres_kwargs({"host": "h", "user": "u"})


class TestMysqlProfile:
    """Test translation of a dbt-mysql profile."""

    def test_server_and_username_spellings(self):
        """dbt-mysql spells these 'server' and 'username'."""
        kwargs = mysql_kwargs({
            "server": "h", "username": "u", "password": "p", "schema": "analytics",
        })
        assert kwargs["host"] == "h"
        assert kwargs["user"] == "u"
        # dbt-mysql's schema is what MySQL calls the database.
        assert kwargs["database"] == "analytics"

    def test_missing_server_is_rejected(self):
        """A MySQL target needs a server."""
        with pytest.raises(ValueError, match="server"):
            mysql_kwargs({"username": "u"})
