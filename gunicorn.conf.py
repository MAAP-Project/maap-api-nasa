# gunicorn.conf.py — MAAP API production server settings.
#
# gunicorn loads ./gunicorn.conf.py from its working directory automatically
# (WORKDIR /maap-api-nasa in the image), at boot and on SIGHUP. Command-line
# flags override anything here, so the compose command should be just
#     gunicorn api.maapapp:app
#
# Sizing rationale (c6i.2xlarge, 8 vCPU / 16 GiB): the API is I/O-bound. A
# request spends well under 1 ms on CPU and the rest waiting on Keycloak,
# Mozart, CMR, GitLab, or Postgres, so capacity is "requests that can be parked
# at once / upstream latency". Threaded workers give that headroom at ~155 MB
# RSS per process; 8 x 16 = 128 in-flight requests vs 5 with the old `-w 5`.

bind = "0.0.0.0:5000"

worker_class = "gthread"
workers = 8
threads = 16

# gthread heartbeats from the worker's main loop, so a long request (granule
# download proxied through the API, slow Mozart call) no longer gets the
# worker SIGKILLed at 30 s as it did with sync workers. Keep as a guard
# against a wedged process.
timeout = 120
graceful_timeout = 30

# Threaded workers honour HTTP keep-alive. Must exceed the load balancer's
# idle timeout (ALB default 60 s) or the LB can reuse a connection the
# backend just closed -> sporadic 502s under load.
keepalive = 75

# Recycle workers to bound slow memory growth over a long day; jitter keeps
# them from all restarting at once.
max_requests = 5000
max_requests_jitter = 500

# api/maapapp.py opens DB connections at import (db.create_all + startup
# tasks). Preloading would share those sockets across forked workers unless
# an engine.dispose() post_fork hook is added, so each worker boots itself.
preload_app = False

accesslog = "-"
errorlog = "-"
loglevel = "info"


def _force_worker_count(server):
    # If a `-w N` flag is still present on the command line it beats this
    # file. This hook does what the TTIN/TTOU signals do so the configured
    # count wins anyway (useful when the file is dropped into a container
    # whose compose command still says `-w 5`). No-op when they already match.
    if server.num_workers != workers:
        server.log.info("gunicorn.conf.py: setting worker count %s -> %s",
                        server.num_workers, workers)
        server.num_workers = workers


def when_ready(server):      # fresh boot / container restart
    _force_worker_count(server)


def on_reload(server):       # SIGHUP of a running master
    _force_worker_count(server)


def post_fork(server, worker):
    # Several outbound requests/urlopen calls in the API carry no timeout
    # (Mozart, CMR, GitLab, tiler). With sync workers the 30 s worker timeout
    # cut those off; with gthread nothing would, so a hung upstream could pin a
    # thread indefinitely. urllib3/requests fall back to the socket default
    # when no timeout is given, so this caps all of them. psycopg2 (libpq) is
    # unaffected.
    import socket
    socket.setdefaulttimeout(60)
