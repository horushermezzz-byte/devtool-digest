#!/usr/bin/env bash
# Plausible CE on a ~1.4 GB box: does it survive sustained load?
# Images are already pulled, so this is a clean cold start + load run.
set -u
export PATH=$HOME/bin:$PATH
export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock
NET=plausible_net
SK=$(printf 'x%.0s' {1..64})

avail() { awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo; }

docker rm -f pl_db pl_ch pl_app >/dev/null 2>&1
docker network rm $NET >/dev/null 2>&1
docker network create $NET >/dev/null 2>&1

echo "MemAvailable at start: $(avail) MB"

docker run -d --name pl_db --network $NET -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=plausible_db postgres:16-alpine >/dev/null
docker run -d --name pl_ch --network $NET -e CLICKHOUSE_SKIP_USER_SETUP=1 \
  --ulimit nofile=262144:262144 clickhouse/clickhouse-server:24-alpine >/dev/null
sleep 35

docker exec pl_ch clickhouse-client --query "CREATE DATABASE IF NOT EXISTS plausible_events_db" >/dev/null 2>&1
echo "clickhouse db created; MemAvailable: $(avail) MB"

docker run --rm --network $NET \
  -e BASE_URL=http://localhost:8105 -e SECRET_KEY_BASE=$SK \
  -e DATABASE_URL=postgres://postgres:postgres@pl_db:5432/plausible_db \
  -e CLICKHOUSE_DATABASE_URL=http://pl_ch:8123/plausible_events_db \
  ghcr.io/plausible/community-edition:v3 db migrate 2>&1 | tail -1

T0=$(date +%s)
docker run -d --name pl_app --network $NET -p 8105:8000 \
  -e BASE_URL=http://localhost:8105 -e SECRET_KEY_BASE=$SK \
  -e DATABASE_URL=postgres://postgres:postgres@pl_db:5432/plausible_db \
  -e CLICKHOUSE_DATABASE_URL=http://pl_ch:8123/plausible_events_db \
  ghcr.io/plausible/community-edition:v3 >/dev/null

READY=""
for i in $(seq 1 120); do
  c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8105/ 2>/dev/null)
  if [ "$c" = "200" ] || [ "$c" = "302" ]; then READY=$(( $(date +%s) - T0 )); break; fi
  sleep 2
done
echo "app ready in ${READY:-NEVER}s"
echo "MemAvailable with full stack: $(avail) MB"
docker stats --no-stream --format '  {{.Name}} {{.MemUsage}}' pl_db pl_ch pl_app

echo "--- sustained load: 300 requests ---"
fail=0; ok=0
for i in $(seq 1 300); do
  c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 8 http://127.0.0.1:8105/ 2>/dev/null)
  case "$c" in 200|302) ok=$((ok+1));; *) fail=$((fail+1));; esac
done
echo "  ok=$ok fail=$fail"
echo "--- post-load ---"
for c in pl_db pl_ch pl_app; do
  docker inspect $c --format "  $c status={{.State.Status}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}" 2>/dev/null
done
docker stats --no-stream --format '  {{.Name}} {{.MemUsage}}' pl_db pl_ch pl_app
echo "  MemAvailable: $(avail) MB"
echo "  kernel OOM events: $(grep -icE 'out of memory|oom-kill' /var/log/kern.log 2>/dev/null || echo 0)"

docker rm -f pl_db pl_ch pl_app >/dev/null 2>&1
docker network rm $NET >/dev/null 2>&1
echo "cleaned up"
