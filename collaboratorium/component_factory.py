from dash import html, dcc, Input, Output, State, ctx, ALL, no_update, MATCH
from datetime import datetime
import json
from visual_customization import dcl
from db import get_dropdown_options


# ==============================================================
# COMPONENT FACTORY
# ==============================================================


def component_for_element(element_config, form_name, value=None):
    """Map element type from YAML to Dash component"""
    element_type = element_config.get("type")
    label = element_config.get("label", element_config["element_id"])
    appearance = element_config.get("appearance", None)

    input_type_mapping = {
        "integer": "number",
        "decimal": "number",
        "email": "email",
        "url": "url",
        "tel": "tel",
        "hidden": "hidden",
    }
    # --- TEXT / NUMBER / DATE ---
    if element_type in ("text", "string", "integer", "decimal", "email", "url", "tel"):
        if appearance == "multiline":
            return html.Div(
                [
                    html.Label(label),
                    dcl.Textarea(
                        id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                        style={'width': '100%'},
                        value=value or "",
                    ),
                ]
            )
        return html.Div(
            [
                html.Label(label),
                dcc.Input(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    type=input_type_mapping.get(element_type, "text"),
                    value=value or "",
                    style={'width': '100%'},
                ),
            ]
        )
    
    # --- hidden ---
    elif element_type == "hidden":
        return dcc.Input(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    type="hidden",
                    value=value or "",
                )

    # --- datetime ---
    elif element_type == "date":
        return html.Div(
            [
                html.Label(label),
                dcc.DatePickerSingle(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    date=value or None,
                ),
            ]
        )
    
    # --- boolean ---
    elif element_type == "boolean":
        # Checklist expects a list for `value` — populate accordingly
        checklist_value = [True] if value else []
        return dcc.Checklist(
            id={"type": "input", "form": form_name, "element": element_config["element_id"]},
            options=[{"label": "True", "value": True}],
            value=checklist_value
        )

    # --- SELECT SINGLE ---
    elif element_type == "select_one":
        if 'list_name' in element_config:
            options = element_config[element_config['list_name']]
        else:
            options = get_dropdown_options(
                element_config["parameters"]["source_table"],
                element_config["parameters"]["value_column"],
                element_config["parameters"]["label_column"],
            )
        return html.Div(
            [
                html.Label(label),
                dcc.Dropdown(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    options=options,
                    value=value,
                    clearable=True,
                ),
            ]
        )

    # --- SELECT MULTIPLE ---
    elif element_type == "select_multiple":
        if 'list_name' in element_config:
            options = element_config[element_config['list_name']]
        else:
            options = get_dropdown_options(
                element_config["parameters"]["source_table"],
                element_config["parameters"]["value_column"],
                element_config["parameters"]["label_column"],
            )
        return html.Div(
            [
                html.Label(label),
                dcc.Dropdown(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    options=options,
                    value=value or [],
                    multi=True,
                    clearable=True,
                ),
            ]
        )

    # --- Subform ---
    elif element_type == "subform":
        subform_block = html.Div([
            html.Div(id={"type": "subform", "form": form_name, "element": element_config["element_id"]}),
            dcc.Store(id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                  data=value)
            ],)
        return subform_block
        

    # --- DEFAULT FALLBACK ---
    return html.Div([html.Label(label), html.Div("Unsupported element type")])

def register_subform_blocks(app, forms_config):
    """Register callbacks per subform in the config."""
    for form_name, fc in forms_config.items():
        value_key_map = {
            "date": "date",
            "datetime": "date",
            "subform": "data",
        }
        state_args = []
        for e_id, e_val in fc["elements"].items():
            if e_val['type'] != 'subform':
                continue
            element_config = dict(element_id=e_id, **e_val)
            
            subform_name = form_name+'-'+element_config["element_id"]
            @app.callback(
                Output({"type": "subform", "form": form_name, "element": element_config["element_id"]}, "children"),
                Input({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
            )
            def call_gen_subform_block(value, _element_config = element_config, _form_name = form_name):
                return generate_subform_block(_element_config, _form_name, value)
            

            @app.callback(
                Output({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
                State({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
                Input({"type": "input", "form": subform_name, "element": ALL}, "value"),
            )
            def handle_subform_block(state, values, _element_config = element_config, _form_name = form_name):
                if ctx.triggered_id is None:
                    return state

                input_keys = [i['id']['element'] for i in ctx.inputs_list[0]]
                flat_input_dict = dict(zip(input_keys, values))
                input_dict = {}
                for key, val in flat_input_dict.items():
                    if '|' in key:
                        parts = key.split('|')
                        assert(len(parts)==2)
                        if parts[0] not in input_dict.keys():
                            input_dict[parts[0]] = {}
                        input_dict[parts[0]][parts[1]] = val
                    else:
                        input_dict[key] = val

                if input_keys == ['failsafe']:
                    return None

                if input_dict['subform_selector'] is not None:
                    subform_key_values = get_dropdown_options(
                        element_config["parameters"]["source_table"],
                        element_config["parameters"]["value_column"],
                        'key_values',
                    )
                    for subform in subform_key_values:
                        if subform['value'] == input_dict['subform_selector']:
                            input_dict[str(subform['value'])] = {}
                            e_cfg = json.loads(subform['label'])
                            for key in e_cfg.keys():
                                input_dict[str(subform['value'])][key] = None

                auto_keep = input_dict.pop('subform_selector')
                new_state = json.loads(state) if state not in [None, ''] else {}
                new_state.update(input_dict)


                for key in list(new_state.keys()):
                    keep=False
                    if type(new_state[key]) is dict:
                        for key2 in new_state[key].keys():
                            if new_state[key][key2] not in [None, '', []]:
                                keep = True
                    elif new_state[key] not in [None, '', []]:
                        keep = True
                    if key == str(auto_keep):
                        keep = True
                    if not keep:
                        new_state.pop(key)

                return json.dumps(new_state, indent=2)
            

def failsafe_div(label, subform_name, value):
    return html.Div(
        [
            html.Label(label+' FAILSAFE: malformed subform data'),
            html.Label('delete the string and add relavant subforms to replace the data'),
            component_for_element(
                element_config=dict(element_id=label, type='string'),
                form_name=subform_name,
                value=value
            ),            
        ], style={'backgroundColor': 'red', 'padding': '10px'}
    )

def generate_subform_block(element_config, form_name, value=None):
    label = element_config.get("label", element_config["element_id"])
    subform_name = form_name+'-'+element_config["element_id"]

    if {"source_table", "value_column", "label_column"}.issubset(set(element_config["parameters"].keys())):
        is_dynamic_form = True
    else:
        is_dynamic_form = False

    failsafe = False
    try:
        value = json.loads(value) if value else {}
    except json.decoder.JSONDecodeError:
        failsafe = True
    
    if type(value) is not dict:
        failsafe = True
        
    
    if failsafe:
        return failsafe_div(label, subform_name, value)
    
    elements = []
    if is_dynamic_form:
        elements = generate_dynamic_subform_elements(element_config, form_name, value)

    subform_block = html.Div(
        [
            html.Label(label+' '),
            *elements,
        ], style={'backgroundColor': 'lightblue', 'padding': '10px'}
    )
    return subform_block

def generate_static_subform_elements(element_config, form_name, value=None):
    label = element_config.get("label", element_config["element_id"])
    subform_name = form_name+'-'+element_config["element_id"]


def generate_dynamic_subform_elements(element_config, form_name, value=None):
    label = element_config.get("label", element_config["element_id"])
    subform_name = form_name+'-'+element_config["element_id"]

    subform_names = get_dropdown_options(
        element_config["parameters"]["source_table"],
        element_config["parameters"]["value_column"],
        element_config["parameters"]["label_column"],
    )
    subform_key_values = get_dropdown_options(
        element_config["parameters"]["source_table"],
        element_config["parameters"]["value_column"],
        'key_values',
    )

    if subform_names is None or subform_key_values is None:
        return html.Div([html.Label(f"No subforms found for {element_config['label']}"),])

    subform_ls = []
    for id in set([d['value'] for l in [subform_key_values, subform_names] for d in l ]):
        subform = {}
        subform['id'] = id
        subform_label = [d['label'] for d in subform_names if d['value'] == id]
        if len(subform_label) != 1:
            print(f"Error in subform, no label for subform id {id}")
        subform['label'] = subform_label[0]
        key_values = [d['label'] for d in subform_key_values if d['value'] == id]
        if len(key_values) != 1:
            print(f"Error in subform, no key_values for subform id {id}")
        subform['key_values'] = json.loads(key_values[0])
        subform_ls.append(subform)


    elements = []
    used_subform_idxs = []
    for key, subform_value in value.items():
        subform = None
        for sf in subform_ls:
            if key == str(sf['id']):
                used_subform_idxs.append(sf['id'])
                subform = sf
                break
        sf_elements = []
        if subform is None:
            sf_elements.append(failsafe_div(key, subform_name, json.dumps(subform_value, indent=2)))
            subform_label = 'failsafe:'+key
        else:
            subform_label = subform['label']
            for field, config in subform['key_values'].items():
                sf_elements.append(component_for_element(
                    element_config=dict(element_id=f'{key}|{field}', **config),
                    form_name=subform_name,
                    value=subform_value[field]
                ))
        elements.append(html.Div(
            [
                html.B(subform_label),
                *sf_elements
            ], style={'border': '1px solid black', 'padding': '10px'}
        ))
    
    available_subforms = [subform for subform in subform_names if subform['value'] not in used_subform_idxs]

    elements += [
        dcc.Dropdown(
            id={"type": "input", "form": subform_name, "element": 'subform_selector'},
            options=available_subforms,
            placeholder='Add new...',
            clearable=True,
        ),
    ]
    return elements


