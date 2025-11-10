from dash import html, dcc, Input, Output, State, ctx, ALL, no_update, MATCH
from datetime import datetime
from db import db_connect, get_latest_entry, get_dropdown_options
from visual_customization import dcl


# ==============================================================
# DATABASE HELPERS
# ==============================================================


def _get_max_id_from_cursor(cur, table_name):
    """Helper to get max ID using an existing cursor."""
    cur.execute(f'SELECT MAX(id) FROM "{table_name}"')
    r = cur.fetchone()
    return int(r[0]) if r and r[0] is not None else 0


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
        return html.Div(
            [
                html.Label(label),
                dcc.Input(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    type=input_type_mapping.get(element_type, "text"),
                    value=value or "",
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
    elif element_type == "datetime":
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

    # --- DEFAULT FALLBACK ---
    return html.Div([html.Label(label), html.Div("Unsupported element type")])


# ==============================================================
# FORM LAYOUT GENERATION
# ==============================================================


def generate_form_layout(form_name, forms_config, object_id=None):
    """Generate a Dash form layout from a form config"""
    record_data = get_latest_entry(form_name, forms_config, object_id) if object_id else {}

    elements = []
    for element_name, element_def in forms_config[form_name].get("elements", {}).items():
        val = record_data.get(element_name) if record_data else None
        element_def = {**element_def, "element_id": element_name}
        elements.append(component_for_element(element_def, form_name=form_name, value=val))

    meta_hidden = []
    for element_name, element_def in forms_config[form_name].get("meta", {}).items():
        val = record_data.get(element_name) if record_data else None
        element_def = {"element_id": element_name, "type": "hidden"}
        meta_hidden.append(component_for_element(element_def, form_name=form_name, value=val))

    meta = html.Div([
        html.Details(
            [
                html.Summary(f"metadata"),
            ] + [html.Div(f"\t{key}: {record_data.get(key, None)}") for key in forms_config[form_name].get("meta", [])]
        ),
    ])

    return html.Div([
        html.H3(f"Edit {forms_config[form_name]['label']}" if object_id else f"Add {forms_config[form_name]['label']}"),
        meta,
        *meta_hidden,
        *elements,
        html.Button("Submit", id={"type": "submit", "form": form_name}, n_clicks=0),
        html.Div(id={"type": "output", "form": form_name})
    ])


# ==============================================================
# CALLBACK REGISTRATION
# ==============================================================

def register_callbacks(app, forms_config):
    """Register one submit callback per form in the config."""
    for form_name, fc in forms_config.items():
        input_ids = [{"type": "input", "form": form_name, "element": e_id} for e_id in fc["elements"].keys()]
        state_args = [State(i, ("date" if "date" in i["element"] else "value")) for i in input_ids]
        meta_ids = [{"type": "input", "form": form_name, "element": e_id} for e_id in fc["meta"].keys()]
        state_args += [State(i, ("date" if "date" in i["element"] else "value")) for i in meta_ids]

        @app.callback(
            Output("out_msg", "children", allow_duplicate=True),
            Output('intermediary-loaded', 'data', allow_duplicate=True),
            Output("form-refresh", "data", allow_duplicate=True),
            Input({"type": "submit", "form": form_name}, "n_clicks"),
            State({"type": "link-input", "table": ALL, "source_col": ALL, "target_col": ALL}, "id"),
            State({"type": "link-input", "table": ALL, "source_col": ALL, "target_col": ALL}, "value"),
            State("current-person-id", "data"),
            *state_args,
            prevent_initial_call=True,
        )
        def handle_submit(n_clicks, link_ids, link_values, person_id, *values, _fc=fc):
            if n_clicks == 0:
                return None, no_update, no_update
            
            conn = db_connect()
            cur = conn.cursor()

            # Part 1: Handle the main object (Person, Initiative, etc.)
            element_ids = list(_fc["elements"].keys())
            data = dict(zip(element_ids + list(_fc["meta"].keys()), values))

            object_id = data.get('id')
            if object_id == "":
                data["id"] = None
                object_id = None
            is_new_object = object_id is None
            
            out_msg = None
            if is_new_object:
                new_id = _get_max_id_from_cursor(cur, _fc["default_table"]) + 1
                object_id = new_id
                data['id'] = new_id
                data['version'] = 1
                data['status'] = 'active'
                out_msg = html.Span(f"✅ Created {_fc["default_table"]} record ID {data['id']}", style={"color": "green"})
            else:
                data['version'] = (data.get('version') or 0) + 1
                out_msg = html.Span(f"✅ Edited {_fc["default_table"]} record ID {data['id']}", style={"color": "green"})
            
            data['timestamp'] = datetime.now().isoformat()
            data['created_by'] = person_id

            cur.execute(f'pragma table_info("{_fc["default_table"]}")')
            r=cur.fetchall()
            cols_sql_ls = []
            placeholders = []
            vals = []
            for col in r:
                col_name = col[1]
                cols_sql_ls.append(col_name)
                placeholders.append("?")
                vals.append(data[col_name])
            cols_sql = ", ".join(cols_sql_ls)
            placeholders = ", ".join(placeholders)
            # Normalize Dash data types before SQL
            for i, v in enumerate(vals):
                if isinstance(v, list):
                    if len(v) == 0:
                        vals[i] = False
                    elif len(v) == 1 and isinstance(v[0], bool):
                        vals[i] = v[0]
                    else:
                        vals[i] = ",".join(map(str, v))
                elif isinstance(v, bool):
                    vals[i] = int(v)
            cur.execute(f'INSERT INTO "{_fc["default_table"]}" ({cols_sql}) VALUES ({placeholders})', vals)

            
            extra_elements = [element for element in data.keys() if element not in cols_sql_ls]
            # Part 2: Handle the Link Table Updates
            for element in extra_elements:
                if "store" in _fc["elements"][element].keys():
                    link_table = _fc["elements"][element]["store"]["link_table"]
                    source_col = _fc["elements"][element]["store"]['source_field']
                    target_col = _fc["elements"][element]["store"]['target_field']
                    
                    link_values = data[element]

                    newly_selected_ids = set(link_values if link_values else [])

                    sql_query = f'''
                    WITH RankedRow AS (
                        -- 1. Find all rows for this ID and rank them
                        --    (highest version gets rn = 1)
                        SELECT
                            id,
                            "{target_col}",
                            "status",
                            -- 1. Group rows by the link id
                            --    and rank them by version, newest = 1.
                            ROW_NUMBER() OVER(PARTITION BY id ORDER BY "version" DESC) as rn
                        FROM "{link_table}"
                        WHERE "{source_col}" = ?
                    )
                    -- 2. Select the top-ranked row (rn = 1)
                    --    only if its status is not 'deleted'
                    SELECT id, "{target_col}"
                    FROM RankedRow
                    WHERE rn = 1 AND "status" != 'deleted'
                    '''
                    cur.execute(sql_query, (object_id,))
                    current_links = {row[1]: row[0] for row in cur.fetchall()}
                    currently_linked_ids = set(current_links.keys())

                    ids_to_add = newly_selected_ids - currently_linked_ids
                    ids_to_remove = currently_linked_ids - newly_selected_ids

                    # Process removals: create a new version with status='deleted'
                    for target_id in ids_to_remove:
                        link_id = current_links[target_id]
                        cur.execute(f'SELECT * FROM "{link_table}" WHERE id = ? ORDER BY version DESC LIMIT 1', (link_id,))
                        cols = [d[0] for d in cur.description]
                        latest_link_data = dict(zip(cols, cur.fetchone()))
                        
                        latest_link_data['version'] += 1
                        latest_link_data['status'] = 'deleted'
                        latest_link_data['timestamp'] = datetime.now().isoformat()
                        
                        l_cols_sql = ", ".join([f'"{k}"' for k in latest_link_data.keys()])
                        l_placeholders = ", ".join(["?"] * len(latest_link_data))
                        cur.execute(f'INSERT INTO "{link_table}" ({l_cols_sql}) VALUES ({l_placeholders})', list(latest_link_data.values()))

                    # Process additions: create a new link record
                    for target_id in ids_to_add:
                        new_link_id = _get_max_id_from_cursor(cur, link_table) + 1
                        insert_data = {
                            'id': new_link_id,
                            'version': 1,
                            'timestamp': datetime.now().isoformat(),
                            'status': 'active',
                            source_col: object_id,
                            target_col: target_id,
                            'created_by': person_id
                        }

                        l_cols_sql = ", ".join([f'"{k}"' for k in insert_data.keys()])
                        l_placeholders = ", ".join(["?"] * len(insert_data))
                        cur.execute(f'INSERT INTO "{link_table}" ({l_cols_sql}) VALUES ({l_placeholders})', list(insert_data.values()))

            conn.commit()
            conn.close()

            return out_msg, datetime.now().isoformat(), int(datetime.now().timestamp()*1000)
