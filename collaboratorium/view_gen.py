from dash import html, dcc, Input, Output, State, ctx, ALL, no_update, MATCH
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto


def build_view_options(config):
    match config['view_config']['selector']:
        case 'dropdown':
            return dcc.Dropdown(
                id='view-selector',
                options=[{'label': view['name'], 'value': view_id} for view_id, view in config['views'].items()],
                value=list(config['views'].keys())[0],
                style={'display': 'inline-block', 'width': '200px', 
                    'verticalAlign': 'bottom',
                },
            )
        case 'button':
            raise NotImplementedError("Implementation idea: https://community.plotly.com/t/multiple-button-dynamic-callbacks/66064")
    

def register_view_callbacks(app, config):
    register_viewcard_callbacks(app, config)

    @app.callback(
        Output('cyto', 'layout'),
        Input('layout-selector', 'value')
    )
    def layout_selector(layout_name):
        layout = config["network_vis"]["layout"].copy()
        if layout_name is not None:
            layout["name"] = layout_name
        return layout


def register_viewcard_callbacks(app, config):
    @app.callback(
        Output("view-container", "children"),
        Input('intermediary-loaded', 'data'),
    )
    def load_view(_):
        card = dbc.Card([
            dbc.CardHeader([
                build_view_options(config),
                dcc.Dropdown(
                    id='layout-selector',
                    options=[
                        'cose-bilkent', 'dagre', 'klay', 'cola', 'spread', 'cose',
                        'breadthfirst', 'concentric', 'grid', 'circle', 'random',
                    ],
                    placeholder='Layout Algorithm...',
                    style={'display': 'inline-block', 'width': '200px', 
                            'verticalAlign': 'bottom', "margin-left": "15px"
                    },
                ),
            ]),
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
        return card