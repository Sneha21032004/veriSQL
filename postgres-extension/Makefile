# Build / install the VeriSQL Postgres extension via PGXS.
#
# Requires the Postgres development headers (`postgresql-server-dev-NN` on
# Debian/Ubuntu, `postgresql-devel` on RHEL/Fedora, `postgresql` via Homebrew
# on macOS) and `pg_config` on PATH.
#
#   sudo make install            # copies files into pg_config --sharedir
#   psql -c "CREATE EXTENSION verisql;"
#
EXTENSION    = verisql
DATA         = verisql--0.1.0.sql
PG_CONFIG   ?= pg_config

PGXS := $(shell $(PG_CONFIG) --pgxs)
include $(PGXS)
