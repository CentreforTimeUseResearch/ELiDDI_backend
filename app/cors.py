from flask import request


# Which pages may call this backend from another origin. The ELiDDI page is
# served from one origin (a study's GitHub Pages site, say) and talks to this
# backend on another, so the browser sends a preflight that must be answered
# (ELiDDI docs/adr/0006) - but only for the origins the operator has named.
#
# Set ELIDDI_CORS_ORIGINS to a comma-separated list of origins, e.g.
#   https://stratus.github.io,https://survey.unil.ch
# A request from a listed origin gets it echoed back (with Vary: Origin); any
# other origin gets no CORS headers, so the browser refuses it. "*" allows every
# origin, which suits local testing only. Unset means no cross-origin access at
# all (right when the page and the backend share an origin).
def parse_origins(value):
    return [item.strip().rstrip('/') for item in (value or '').split(',') if item.strip()]


def add_cors(app):
    allowed = app.config['CORS_ORIGINS']

    @app.after_request
    def set_headers(response):
        origin = request.headers.get('Origin', '').rstrip('/')
        if '*' in allowed:
            response.headers['Access-Control-Allow-Origin'] = '*'
        elif origin and origin in allowed:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers.add('Vary', 'Origin')
        else:
            return response
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
        # lets the page read how long to wait after a 429
        response.headers['Access-Control-Expose-Headers'] = 'Retry-After'
        return response
