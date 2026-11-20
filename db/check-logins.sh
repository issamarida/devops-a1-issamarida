#!/bin/sh
# Proves what brief section 1a asks of the logins: each service's login reaches
# its own database and is refused on the other one.
#
# Run it from the repo root while the compose database is up:
#     docker compose up -d --wait db && docker compose run --rm db-init
#     sh db/check-logins.sh
# CI runs it on every push.
set -eu

# can_open <service> <database>: succeeds when that service's login can open the database.
can_open() {
    docker compose exec -T db /bin/sh -c "
        SQLCMDPASSWORD=\$(cat /run/local-secrets/$1_password) \
        /opt/mssql-tools18/bin/sqlcmd -S localhost -U $1_user -d $2 -C -b -l 5 \
            -Q 'SELECT 1' > /dev/null 2>&1"
}

failed=0

for service in watchlist alerts; do
    if can_open "$service" "$service"; then
        echo "ok: ${service}_user opens the $service database"
    else
        echo "FAILED: ${service}_user cannot open its own database"
        failed=1
    fi
done

if can_open watchlist alerts; then
    echo "FAILED: watchlist_user can open the alerts database"
    failed=1
else
    echo "ok: watchlist_user is refused on the alerts database"
fi

if can_open alerts watchlist; then
    echo "FAILED: alerts_user can open the watchlist database"
    failed=1
else
    echo "ok: alerts_user is refused on the watchlist database"
fi

exit "$failed"
