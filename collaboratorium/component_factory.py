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

    # --- Tag group ---
    elif element_type == "tag":
        tag_block = html.Div([
            html.Div(id={"type": "subform", "form": form_name, "element": element_config["element_id"]}),
            dcc.Store(id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                  data=value)
            ],)
        return tag_block
        

    # --- DEFAULT FALLBACK ---
    return html.Div([html.Label(label), html.Div("Unsupported element type")])

def register_tag_blocks(app, forms_config):
    """Register callbacks per tag in the config."""
    for form_name, fc in forms_config.items():
        value_key_map = {
            "date": "date",
            "datetime": "date",
            "tag": "data",
        }
        state_args = []
        for e_id, e_val in fc["elements"].items():
            if e_val['type'] != 'tag':
                continue
            element_config = dict(element_id=e_id, **e_val)
            
            subform_name = form_name+'-'+element_config["element_id"]
            @app.callback(
                Output({"type": "subform", "form": form_name, "element": element_config["element_id"]}, "children"),
                Input({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
            )
            def call_gen_tag_block(value, _element_config = element_config, _form_name = form_name):
                return generate_tag_block(_element_config, _form_name, value)
            

            @app.callback(
                Output({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
                State({"type": "input", "form": form_name, "element": element_config["element_id"]}, "data"),
                Input({"type": "input", "form": subform_name, "element": ALL}, "value"),
            )
            def handle_tag_block(state, values, _element_config = element_config, _form_name = form_name):
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

                if input_dict['tag_group_selector'] is not None:
                    tag_key_values = get_dropdown_options(
                        element_config["parameters"]["source_table"],
                        element_config["parameters"]["value_column"],
                        'key_values',
                    )
                    for tag_group in tag_key_values:
                        if tag_group['value'] == input_dict['tag_group_selector']:
                            input_dict[str(tag_group['value'])] = {}
                            e_cfg = json.loads(tag_group['label'])
                            for key in e_cfg.keys():
                                input_dict[str(tag_group['value'])][key] = None

                auto_keep = input_dict.pop('tag_group_selector')
                new_state = json.loads(state) if state is not None else {}
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
            html.Label(label+' FAILSAFE: malformed tag data'),
            html.Label('delete the string tags out and replace them with tags compatible with the tag groups'),
            component_for_element(
                element_config=dict(element_id=label, type='string'),
                form_name=subform_name,
                value=value
            ),            
        ], style={'backgroundColor': 'red', 'padding': '10px'}
    )

def generate_tag_block(element_config, form_name, value=None):
    label = element_config.get("label", element_config["element_id"])
    subform_name = form_name+'-'+element_config["element_id"]

    failsafe = False
    try:
        value = json.loads(value) if value else {}
    except json.decoder.JSONDecodeError:
        failsafe = True
    
    if type(value) is not dict:
        failsafe = True
        
    
    if failsafe:
        return failsafe_div(label, subform_name, value)

    

    tag_group_names = get_dropdown_options(
        element_config["parameters"]["source_table"],
        element_config["parameters"]["value_column"],
        element_config["parameters"]["label_column"],
    )
    tag_key_values = get_dropdown_options(
        element_config["parameters"]["source_table"],
        element_config["parameters"]["value_column"],
        'key_values',
    )

    if tag_group_names is None or tag_key_values is None:
        return html.Div([html.Label("No tag groups"),])

    tag_group_ls = []
    for id in set([d['value'] for l in [tag_key_values, tag_group_names] for d in l ]):
        tag_group = {}
        tag_group['id'] = id
        tag_label = [d['label'] for d in tag_group_names if d['value'] == id]
        if len(tag_label) != 1:
            print(f"Error in tags, no label for tag group id {id}")
        tag_group['label'] = tag_label[0]
        key_values = [d['label'] for d in tag_key_values if d['value'] == id]
        if len(key_values) != 1:
            print(f"Error in tags, no key_values for tag group id {id}")
        tag_group['key_values'] = json.loads(key_values[0])
        tag_group_ls.append(tag_group)


    elements = []
    used_tag_group_idxs = []
    for key, tag_value in value.items():
        tag_group = None
        for tg in tag_group_ls:
            if key == str(tg['id']):
                used_tag_group_idxs.append(tg['id'])
                tag_group = tg
                break
        tg_elements = []
        if tag_group is None:
            tg_elements.append(failsafe_div(key, subform_name, json.dumps(tag_value, indent=2)))
            tag_group_label = 'failsafe:'+key
        else:
            tag_group_label = tag_group['label']
            for field, config in tag_group['key_values'].items():
                tg_elements.append(component_for_element(
                    element_config=dict(element_id=f'{key}|{field}', **config),
                    form_name=subform_name,
                    value=tag_value[field]
                ))
        elements.append(html.Div(
            [
                html.B(tag_group_label),
                *tg_elements
            ], style={'border': '1px solid black', 'padding': '10px'}
        ))
    
    available_tag_groups = [tag_group for tag_group in tag_group_names if tag_group['value'] not in used_tag_group_idxs]

    tag_block = html.Div(
        [
            html.Label(label+' '),
            *elements,
            html.Label('Add form:'),
            dcc.Dropdown(
                id={"type": "input", "form": subform_name, "element": 'tag_group_selector'},
                options=available_tag_groups,
                placeholder='Add Tag Group to Node',
                clearable=True,
            ),
        ], style={'backgroundColor': 'lightblue', 'padding': '10px'}
    )
    return tag_block
