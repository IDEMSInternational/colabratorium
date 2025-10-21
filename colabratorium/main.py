# main.py
from dash import Dash, html, dcc, Input, Output, ctx
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
from pydbml import PyDBML

from form_gen import generate_form_layout, register_callbacks
from visual_customization import stylesheet, title
from db import build_elements_from_db, init_db


with open("schema.dbml") as f:
    dbml = PyDBML(f)

init_db()

app = Dash(title, title=title, external_stylesheets=[dbc.themes.BOOTSTRAP],)


app.layout = dbc.Container([
    dcc.Store(id='selected-action', data=None),
    dcc.Store(id='selected-node', data=None),
    dcc.Store(id='intermediary-loaded', data=False),

    dbc.Row(dbc.Col(html.H2(title))),

    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader('Graph'),
                dbc.CardBody([
                    dcc.Checklist(id='node-type-filter', options=[{'label': t, 'value': t} for t in ['people', 'organisations', 'initiatives', 'activities', 'contracts']], value=['people','organisations','initiatives','activities', 'contracts'], inline=True),
                    dcc.Dropdown(id='people-filter', multi=True, placeholder='Filter by people...'),
                    dbc.Checklist(id='show-deleted', options=[{'label':'Show deleted','value':'show'}], value=[], inline=True),
                    dcc.Slider(id='degree-filter', min=1, max=5, step=1, value=1),
                    cyto.Cytoscape(id='cyto', elements=[], style={'width': '100%', 'height': '600px'}, layout={'name': 'cose'}, stylesheet=stylesheet)
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

                    html.Div(id="results", style={"marginLeft": "35%"})
                ]))
            ])
        ], width=4)
    ])
], fluid=True)


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
    return generate_form_layout(table, dbml=dbml)


def show_node_form(tap_node):
    try:
        table_name, id_str = tap_node['id'].split('-', 1)
        object_id = int(id_str)
    except (ValueError, TypeError):
        print(f"Could not parse node ID: {tap_node.get('id')}")
        return html.Div("Invalid node clicked.")

    table = next((t for t in dbml.tables if t.name == table_name), None)
    if not table:
         return html.Div(f"Error: Table '{table_name}' not in DBML.")
    return generate_form_layout(table, object_id=object_id, dbml=dbml)


def show_edge_form(tap_edge):
    table_name = tap_edge.get('table_name')
    object_id = tap_edge.get('object_id')

    if not table_name or object_id is None:
        return html.P(f"This edge ({tap_edge.get('label')}) is not editable.")

    table = next((t for t in dbml.tables if t.name == table_name), None)
    if not table:
         return html.Div(f"Error: Table '{table_name}' not in DBML.")

    return generate_form_layout(table, object_id=object_id, dbml=dbml)
    

def load_dropdown_options(node_type):
    """Return list of {'label','value'} options for given node_type (Person/Initiative)."""
    # Build options directly from the authoritative DB elements (avoid reading intermediary cache)
    try:
        elements = build_elements_from_db(include_deleted=False, node_types=[node_type])
        nodes = [e for e in elements if 'source' not in e.get('data', {}) and e.get('data', {}).get('type') == node_type]
        return [{'label': n['data'].get('label'), 'value': n['data'].get('id')} for n in nodes]
    except Exception:
        return []

@app.callback(
    Output('people-filter', 'options'),
    Input('intermediary-loaded', 'data'),
)
def populate_people_filter(loaded):
    return load_dropdown_options('people')


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
    # determine whether to include deleted entities/links
    include_deleted = bool(show_deleted and 'show' in show_deleted)

    # Build elements directly from the authoritative DB using the active filters
    elements = build_elements_from_db(
        include_deleted=include_deleted,
        node_types=selected_types,
        people_selected=people_selected,
        degree=degree,
    )

    if not elements:
        return []
    return elements




if __name__ == "__main__":
    import os

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
    app.run(host=host, port=port, debug=debug)
