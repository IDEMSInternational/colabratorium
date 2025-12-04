from dash import html, dcc, Input, Output, State, ctx, ALL, no_update, MATCH
from datetime import datetime
from db import db_connect, get_latest_entry

from analytics import analytics_log
from auth import login_required
from component_factory import component_for_element, register_subform_blocks


# ==============================================================
# DATABASE HELPERS
# ==============================================================


def _get_max_id_from_cursor(cur, table_name):
    """Helper to get max ID using an existing cursor."""
    cur.execute(f'SELECT MAX(id) FROM "{table_name}"')
    r = cur.fetchone()
    return int(r[0]) if r and r[0] is not None else 0


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

def register_form_callbacks(app, config):
    register_click_callbacks(app, config)
    register_submit_callbacks(app, config.get("forms", {}))
    register_subform_blocks(app, config.get("forms", {}))

def register_click_callbacks(app, config):
    forms_config = config.get("forms", {})

    @app.callback(
        Output("form-container", "children"),
        Input("table-selector", "value"),
        Input('cyto', 'tapNodeData'),
        Input('cyto', 'tapEdgeData'),
        State("current-person-id", "data"),
        Input("form-refresh", "data"),
    )
    def load_form(table_name, tap_node, tap_edge, person_id, refresh_signal):
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
        
        if trigger == "form-refresh.data":
            return html.Div("Select a table or click a node/edge in the graph.")

        # If the table selector is the trigger, show the add form (explicit user choice)
        if trigger and trigger.startswith("table-selector"):
            if table_name:
                return show_add_form(table_name, person_id)
            return "Select a table"

        # If cyto's tapEdgeData triggered, prefer edge form
        if trigger and "cyto.tapEdgeData" in trigger:
            if tap_edge:
                # pick edge if it has editable table info
                return show_edge_form(tap_edge, person_id)

        # If cyto's tapNodeData triggered, prefer node form
        if trigger and "cyto.tapNodeData" in trigger:
            if tap_node:
                return show_node_form(tap_node, person_id)

        # No explicit trigger (initial or programmatic call).
        # Fall back to previous behavior but prefer node/edge when both present.
        if table_name and not (tap_node or tap_edge):
            return show_add_form(table_name, person_id)

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
                return show_edge_form(tap_edge, person_id)

        if tap_node:
            if not tap_edge or _is_node_newer(tap_node, tap_edge):
                return show_node_form(tap_node, person_id)

        # If nothing else, show a helpful message
        return html.Div("Select a table or click a node/edge in the graph.")


    def show_add_form(table_name, person_id):
        if not table_name:
            return "Select a table"
        form_name = config["default_forms"][table_name]
        return login_required(generate_form_layout)(form_name, forms_config=forms_config)


    def show_node_form(tap_node, person_id):
        try:
            table_name, id_str = tap_node['id'].split('-', 1)
            object_id = int(id_str)
        except (ValueError, TypeError):
            return html.Div("Invalid node clicked.")
        form_name = config["default_forms"].get(table_name, None)
        if not form_name:
            return html.Div(f"Error: Table '{table_name}' not in config['default_forms'].")
        
        analytics_log(person_id, table_name, object_id)
        return login_required(generate_form_layout)(form_name, forms_config=forms_config, object_id=object_id)


    def show_edge_form(tap_edge, person_id):
        table_name = tap_edge.get('table_name')
        object_id = tap_edge.get('object_id')
        analytics_log(person_id, table_name, object_id)
        if not table_name or object_id is None:
            return html.P(f"This edge ({tap_edge.get('label')}) is not editable.")
        form_name = config["default_forms"].get(table_name, None)
        if not form_name:
            return html.Div(f"Error: Table '{table_name}' not in config['default_forms'].")
        return login_required(generate_form_layout)(form_name, forms_config=forms_config, object_id=object_id)


def register_submit_callbacks(app, forms_config):
    """Register one submit callback per form in the config."""
    for form_name, fc in forms_config.items():
        input_ids = [{"type": "input", "form": form_name, "element": e_id} for e_id in fc["elements"].keys()]
        value_key_map = {
            "date": "date",
            "datetime": "date",
            "subform": "data",
        }
        meta_ids = [{"type": "input", "form": form_name, "element": e_id} for e_id in fc["meta"].keys()]
        state_args = []
        for e_id, e_val in (fc["elements"] | fc["meta"]).items():
            i = {"type": "input", "form": form_name, "element": e_id}
            try:
                value_key = value_key_map.get(e_val['type'], "value")
            except KeyError:
                value_key = 'value'
            state_args.append(State(i, value_key))

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
