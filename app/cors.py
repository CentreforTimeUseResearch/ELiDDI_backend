# Any origin is allowed: this backend is only for local testing for now.
# The ELiDDI page posts application/json from another origin, so the browser
# sends a preflight that must be answered (ELiDDI docs/adr/0006).
def add_cors(app):
    @app.after_request
    def set_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        return response
