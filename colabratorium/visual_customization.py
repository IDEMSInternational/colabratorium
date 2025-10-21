from dash import dcc

# Set title
title = 'Colabratorium'

# Define which tables should be treated as nodes in the graph
NODE_TABLES = {
    'people',
    'organisations',
    'initiatives',
    'activities',
    'contracts',
    # Add other tables here if they should be nodes
}

# dash component library
dcl = dcc

# Cytoscape stylesheet: show labels and style node types
stylesheet = [
    {
        'selector': 'node',
        'style': {
            'label': 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '12px',
            'width': '60px',
            'height': '60px'
        }
    },
    {'selector': '.people', 'style': {'background-color': '#FF69B4', 'shape': 'ellipse'}},
    {'selector': '.organisations', 'style': {'background-color': '#87CEEB', 'shape': 'rectangle'}},
    {'selector': '.initiatives', 'style': {'background-color': '#98FB98', 'shape': 'round-diamond'}},
    {'selector': '.activities', 'style': {'background-color': '#F0E68C', 'shape': 'hexagon'}},
    {'selector': 'edge', 'style': {'curve-style': 'bezier', 'target-arrow-shape': 'triangle', 'label': 'data(label)', 'font-size': '10px'}}
]

