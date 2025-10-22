# main.py
import os
from functools import wraps
from flask import Flask, session, redirect, url_for, request
from flask_session import Session
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from datetime import datetime

from dash import Dash, html, dcc, Input, Output, ctx
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
from pydbml import PyDBML

from form_gen import generate_form_layout, register_callbacks
from visual_customization import stylesheet, title, NODE_TABLES
from db import build_elements_from_db, init_db, db_connect


# ---------------------------------------------------------
# Database initialization
# ---------------------------------------------------------
with open("schema.dbml") as f:
    dbml = PyDBML(f)
init_db()


# ---------------------------------------------------------
# Flask + OAuth setup
# ---------------------------------------------------------

load_dotenv()
server = Flask(__name__)
server.secret_key = os.environ.get("SECRET_KEY")
server.config["SESSION_TYPE"] = "filesystem"
server.config["SESSION_PERMANENT"] = False
Session(server)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
OAUTH_REDIRECT_URI = os.environ.get("OAUTH_REDIRECT_URI", "http://localhost:8050/auth/callback")

oauth = OAuth(server)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    access_token_url="https://oauth2.googleapis.com/token",
    access_token_params=None,
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    authorize_params=None,
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ---------------------------------------------------------
# Auth routes and helpers
# ---------------------------------------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

@server.before_request
def simulate_local_login():
    """Automatically log in as a fake user for local development."""
    in_docker = os.getcwd() == "/app"
    debug_env = os.environ.get("DEBUG", None)
    if not in_docker and (debug_env is None or debug_env.lower() in ("1", "true", "yes", "on")):
        if "user" not in session:
            session["user"] = {
                "sub": "localdev",
                "email": "localhost@example.com",
                "name": "Local Developer",
                "picture": None,
            }

@server.route("/login")
def login():
    redirect_uri = OAUTH_REDIRECT_URI
    return oauth.google.authorize_redirect(redirect_uri)


@server.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    userinfo = oauth.google.get("userinfo").json()
    if not userinfo.get("email").endswith("@idems.international"):
        return redirect("unauthorized")
    session["user"] = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name"),
        "picture": userinfo.get("picture"),
    }
    next_url = request.args.get("next") or "/"
    return redirect(next_url)


@server.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")


# ---------------------------------------------------------
# Auth helpers for integration
# ---------------------------------------------------------
def get_person_id_for_user(user):
    """Map the logged-in user to a person.id in the DB, creating if missing."""
    if not user or not user.get("email"):
        return None

    conn = db_connect()
    cur = conn.cursor()
    # Try to find a person with this email
    cur.execute("SELECT id FROM people WHERE email = ? AND status != 'deleted' ORDER BY version DESC LIMIT 1", (user["email"],))
    row = cur.fetchone()
    if row:
        return row[0]

    # Create a new record if not found
    cur.execute("SELECT MAX(id) FROM people")
    max_id = cur.fetchone()[0] or 0
    new_id = max_id + 1
    now = datetime.now().isoformat()
    cur.execute(
        'INSERT INTO people (id, name, email, status, version, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (new_id, user.get("name", user["email"]), user["email"], "active", 1, now)
    )
    conn.commit()
    conn.close()
    return new_id


# ---------------------------------------------------------
# Dash app setup
# ---------------------------------------------------------
app = Dash(
    title,
    title=title,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    server=server,
    suppress_callback_exceptions=True,
)

app.layout = dbc.Container([
    dcc.Store(id='selected-action', data=None),
    dcc.Store(id='selected-node', data=None),
    dcc.Store(id='intermediary-loaded', data=False),
    dcc.Store(id="current-person-id", data=None),

    dbc.Row([
        dbc.Col(html.H2(title)),
        dbc.Col([
            html.Div(id="login-area")
        ])
    ]),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader('Graph'),
                dbc.CardBody([
                    dcc.Checklist(id='node-type-filter',
                                  options=[{'label': t, 'value': t} for t in
                                           NODE_TABLES],
                                  value=['people', 'organisations', 'initiatives', 'activities', 'contracts'],
                                  inline=True),
                    dcc.Dropdown(id='people-filter', multi=True, placeholder='Filter by people...'),
                    dbc.Checklist(id='show-deleted', options=[{'label': 'Show deleted', 'value': 'show'}],
                                  value=[], inline=True),
                    dcc.Slider(id='degree-filter', min=1, max=5, step=1, value=1),
                    cyto.Cytoscape(id='cyto', elements=[], style={'width': '100%', 'height': '600px'},
                                   layout={'name': 'cose'}, stylesheet=stylesheet)
                ])
            ])
        ], width=8),

        dbc.Col([
            dbc.Card([
                dbc.CardBody(html.Div([
                    html.Div([
                        html.H2("Tables"),
                        dcc.Dropdown(
                            id="table-selector",
                            options=[{"label": t.name, "value": t.name} for t in dbml.tables],
                        ),
                        html.Div(id="form-container")
                    ], style={"width": "100%", "float": "left"}),

                    html.Div(id="results", style={"marginLeft": "35%"}),

                ]))
            ])
        ], width=4)
    ])
], fluid=True)


# ---------------------------------------------------------
# Dash callbacks
# ---------------------------------------------------------
@app.callback(Output("login-area", "children"), Input("table-selector", "value"))
def show_login_area(_):
    user = session.get("user")
    if user:
        return html.Div([
            html.Img(src=user["picture"], style={"height": "40px", "marginRight": "10px"}),
            html.Span(f"Logged in as {user['name']} ({user['email']})"),
            html.Br(),
            html.A("Logout", href="/logout")
        ])
    else:
        return html.Div(html.A("Login with Google", href="/login"))


@app.callback(
    Output("current-person-id", "data"),
    Input("intermediary-loaded", "data"),  # or whatever triggers your load
)
def populate_person_id(_):
    person_id = get_person_id_for_user(session["user"])
    return person_id


@app.callback(
    Output("form-container", "children"),
    Input("table-selector", "value"),
    Input('cyto', 'tapNodeData'),
    Input('cyto', 'tapEdgeData')
)
def load_form(table_name, tap_node, tap_edge):
    """
    Display either:
      - add form (when table-selector triggered),
      - node form (when cyto tapNode triggered),
      - edge form (when cyto tapEdge triggered).

    Uses ctx.triggered to prefer the *actual* trigger rather than just presence of table_name.
    """
    # determine which input actually triggered this callback
    trigger = None
    if ctx.triggered:
        # ctx.triggered is a list like [{'prop_id': 'table-selector.value', 'value': ...}]
        trigger = ctx.triggered[0].get('prop_id', '')

    # If the table selector is the trigger, show the add form (explicit user choice)
    if trigger and trigger.startswith("table-selector"):
        if table_name:
            return show_add_form(table_name)
        return "Select a table"

    # If cyto's tapEdgeData triggered, prefer edge form
    if trigger and "cyto.tapEdgeData" in trigger:
        if tap_edge:
            # pick edge if it has editable table info
            return show_edge_form(tap_edge)

    # If cyto's tapNodeData triggered, prefer node form
    if trigger and "cyto.tapNodeData" in trigger:
        if tap_node:
            return show_node_form(tap_node)

    # No explicit trigger (initial or programmatic call).
    # Fall back to previous behavior but prefer node/edge when both present.
    if table_name and not (tap_node or tap_edge):
        return show_add_form(table_name)

    # Helper to decide which of node/edge is the most recent when both are present
    def _is_node_newer(n, e):
        try:
            nt = int(n.get('timeStamp')) if n and n.get('timeStamp') is not None else None
        except Exception:
            nt = None
        try:
            et = int(e.get('timeStamp')) if e and e.get('timeStamp') is not None else None
        except Exception:
            et = None
        if nt is None and et is None:
            return False
        if nt is None:
            return False
        if et is None:
            return True
        return nt >= et

    # If an edge exists and is newer than the node, show edge form
    if tap_edge:
        if not tap_node or _is_node_newer(tap_edge, tap_node):
            return show_edge_form(tap_edge)

    if tap_node:
        if not tap_edge or _is_node_newer(tap_node, tap_edge):
            return show_node_form(tap_node)

    # If nothing else, show a helpful message
    return html.Div("Select a table or click a node/edge in the graph.")


def show_add_form(table_name):
    if not table_name:
        return "Select a table"
    table = next(t for t in dbml.tables if t.name == table_name)
    return login_required(generate_form_layout)(table, dbml=dbml)


def show_node_form(tap_node):
    try:
        table_name, id_str = tap_node['id'].split('-', 1)
        object_id = int(id_str)
    except (ValueError, TypeError):
        return html.Div("Invalid node clicked.")
    table = next((t for t in dbml.tables if t.name == table_name), None)
    if not table:
        return html.Div(f"Error: Table '{table_name}' not in DBML.")
    
    return login_required(generate_form_layout)(table, object_id=object_id, dbml=dbml)


def show_edge_form(tap_edge):
    table_name = tap_edge.get('table_name')
    object_id = tap_edge.get('object_id')
    if not table_name or object_id is None:
        return html.P(f"This edge ({tap_edge.get('label')}) is not editable.")
    table = next((t for t in dbml.tables if t.name == table_name), None)
    if not table:
        return html.Div(f"Error: Table '{table_name}' not in DBML.")
    return login_required(generate_form_layout)(table, object_id=object_id, dbml=dbml)


@app.callback(Output('people-filter', 'options'), Input('intermediary-loaded', 'data'))
def populate_people_filter(_):
    try:
        elements = build_elements_from_db(include_deleted=False, node_types=['people'])
        nodes = [e for e in elements if 'source' not in e.get('data', {}) and e.get('data', {}).get('type') == 'people']
        return [{'label': n['data'].get('label'), 'value': n['data'].get('id')} for n in nodes]
    except Exception:
        return []


register_callbacks(app, dbml)


@app.callback(
    Output('cyto', 'elements'),
    Input('intermediary-loaded', 'data'),
    Input('node-type-filter', 'value'),
    Input('people-filter', 'value'),
    Input('show-deleted', 'value'),
    Input('degree-filter', 'value'),
)
def refresh_graph(_loaded, selected_types, people_selected, show_deleted, degree):
    include_deleted = bool(show_deleted and 'show' in show_deleted)

    # Build elements directly from the authoritative DB using the active filters
    elements = login_required(build_elements_from_db)(
        include_deleted=include_deleted,
        node_types=selected_types,
        people_selected=people_selected,
        degree=degree,
    )
    return elements or []


# ---------------------------------------------------------
# Server startup
# ---------------------------------------------------------
if __name__ == "__main__":
    in_docker = os.getcwd() == "/app"

    # Default to 0.0.0.0 when in Docker so the container port is reachable from host.
    default_host = "0.0.0.0" if in_docker else "127.0.0.1"

    host = os.environ.get("HOST", default_host)
    port = int(os.environ.get("PORT", "8050"))
    debug_env = os.environ.get("DEBUG", None)
    if debug_env is None:
        # Default debug to True only for local development
        debug = not in_docker
    else:
        debug = debug_env.lower() in ("1", "true", "yes", "on")

    print(f"Starting server on {host}:{port} (in_docker={in_docker}, debug={debug})")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
