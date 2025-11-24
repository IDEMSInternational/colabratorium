# main.py
import os
from datetime import datetime

from auth import server, login_required, register_auth_callbacks

from dash import Dash, html, dcc, Input, Output, State, ctx
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto

from form_gen import register_form_callbacks
from db import build_elements_from_db, init_db, db_connect

from analytics import init_db as analytics_init_db
from config_parser import load_config


# ---------------------------------------------------------
# Config Load
# ---------------------------------------------------------
config = load_config("config.yaml")
forms_config = config.get("forms", {})

# ---------------------------------------------------------
# Database initialization
# ---------------------------------------------------------
init_db(config)
analytics_init_db()

# ---------------------------------------------------------
# Dash app setup
# ---------------------------------------------------------

cyto.load_extra_layouts()
app = Dash(
    config["title"],
    title=config["title"],
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    server=server,
    suppress_callback_exceptions=True,
)

app.layout = dbc.Container([
    dcc.Store(id='selected-action', data=None),
    dcc.Store(id='selected-node', data=None),
    dcc.Store(id='intermediary-loaded', data=False),
    dcc.Store(id="current-person-id", data=None),
    dcc.Store(id="form-refresh", data=False),

    dbc.Row([
        dbc.Col(html.H2(config["title"])),
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
                                           config["node_tables"]],
                                  value=config["node_tables"],
                                  inline=True),
                    dcc.Dropdown(id='people-filter', multi=True, placeholder='Filter by people or initiative...'),
                    dbc.Checklist(id='show-deleted', options=[{'label': 'Show deleted', 'value': 'show'}],
                                  value=[], inline=True, style={'display': 'none'}),
                    dcc.Slider(id='degree-filter', min=1, max=5, step=1, value=1),
                    dcc.Checklist(id='node-type-degree-filter',
                                  options=[{'label': t, 'value': t} for t in
                                           config["node_tables"]],
                                  value=config["node_tables"],
                                  inline=True),
                    cyto.Cytoscape(id='cyto', elements=[], style={'width': '100%', 'height': '600px'},
                                   layout=config["network_vis"]["layout"], stylesheet=config["network_vis"]["stylesheet"])
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
                            options=[{"label": t, "value": t} for t in config["tables"].keys()],
                        ),
                        html.Div(id="form-container"),
                        html.Div(id="out_msg", children=[]),
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
register_auth_callbacks(app)


@app.callback(Output('people-filter', 'options'), Input('intermediary-loaded', 'data'))
def populate_people_filter(_):
    try:
        elements = login_required(build_elements_from_db)(config, include_deleted=False, node_types=['people', 'initiatives'])
        nodes = [e for e in elements if 'source' not in e.get('data', {}) and e.get('data', {}).get('type') in ['people', 'initiatives']]
        return [{'label': n['data'].get('label'), 'value': n['data'].get('id')} for n in nodes]
    except Exception:
        return []


register_form_callbacks(app, config)


@app.callback(
    Output('cyto', 'elements'),
    Input('intermediary-loaded', 'data'),
    Input('node-type-filter', 'value'),
    Input('people-filter', 'value'),
    Input('show-deleted', 'value'),
    Input('degree-filter', 'value'),
    Input('node-type-degree-filter', 'value'),
)
def refresh_graph(_loaded, selected_types, people_selected, show_deleted, degree, degree_types):
    include_deleted = bool(show_deleted and 'show' in show_deleted)

    # Build elements directly from the authoritative DB using the active filters
    elements = login_required(build_elements_from_db)(
        config,
        include_deleted=include_deleted,
        node_types=selected_types,
        people_selected=people_selected,
        degree=degree,
        degree_types=degree_types
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
