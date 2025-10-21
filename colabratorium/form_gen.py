from dash import html, dcc, Input, Output, State, ctx, ALL, no_update
from datetime import datetime
from db import db_connect
from visual_customization import dcl, NODE_TABLES


# ==============================================================
# DATABASE HELPERS
# ==============================================================

def get_dropdown_options(conn, table_name, dbml=None):
    """
    Fetch dropdown options for a foreign key reference.
    Shows 'name' column as label if present, otherwise uses ID.
    """
    cur = conn.cursor()
    label_col = "id"
    if dbml:
        table = next((t for t in dbml.tables if t.name == table_name), None)
        if table and any(c.name == "name" for c in table.columns):
            label_col = "name"

    try:
        cur.execute(f'SELECT id, "{label_col}" FROM "{table_name}" WHERE status != \'deleted\'')
        rows = cur.fetchall()
        return [{"label": str(r[1]), "value": r[0]} for r in rows]
    except Exception as e:
        print(f"[WARN] Error fetching options for {table_name}: {e}")
        return []


def get_latest_record(conn, table_name, object_id):
    """Return the most recent non-deleted record for the given id."""
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            SELECT * FROM "{table_name}"
            WHERE id = ? AND status != 'deleted'
            ORDER BY version DESC
            LIMIT 1
            """,
            (object_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    except Exception as e:
        print(f"Error fetching record for {table_name}: {e}")
        return {}


def _get_max_id_from_cursor(cur, table_name):
    """Helper to get max ID using an existing cursor."""
    cur.execute(f'SELECT MAX(id) FROM "{table_name}"')
    r = cur.fetchone()
    return int(r[0]) if r and r[0] is not None else 0


# ==============================================================
# DBML STRUCTURE PARSING
# ==============================================================

def build_reference_index(dbml):
    """Build mappings of foreign key relationships."""
    fk_map = {}  # (child_table, child_column) -> (parent_table, parent_column)
    for ref in dbml.refs:
        col1 = ref.col1[0]
        col2 = ref.col2[0]
        child = (col1.table.name, col1.name)
        parent = (col2.table.name, col2.name)
        fk_map[child] = parent
    return fk_map


# ==============================================================
# COMPONENT FACTORY
# ==============================================================

def component_for_column(col, conn, fk_map, dbml=None, value=None):
    """Return an appropriate Dash component for a DBML column.
       Accepts `value` to pre-populate the component at construction time.
    """
    tname = col.type.lower()
    table_col_key = (col.table.name, col.name)

    # Handle foreign key relationships
    if table_col_key in fk_map:
        ref_table, _ = fk_map[table_col_key]
        options = get_dropdown_options(conn, ref_table, dbml=dbml)
        return dcl.Dropdown(
            id={"type": "input", "table": col.table.name, "column": col.name},
            options=options,
            placeholder=f"Select from {ref_table}",
            value=value
        )

    # Handle primitive types
    elif tname in ("varchar", "text", "char", "string"):
        if col.name.lower() in ("description", "tags"):
            return dcl.Textarea(
                id={"type": "input", "table": col.table.name, "column": col.name},
                placeholder=col.name, style={'width': '100%'},
                value=value
            )
        return dcl.Input(
            id={"type": "input", "table": col.table.name, "column": col.name},
            type="text", placeholder=col.name, style={'width': '100%'},
            value=value
        )
    elif tname in ("integer", "int"):
        return dcl.Input(
            id={"type": "input", "table": col.table.name, "column": col.name},
            type="number", placeholder=col.name,
            value=value
        )
    elif tname == "boolean":
        # Checklist expects a list for `value` — populate accordingly
        checklist_value = [True] if value else []
        return dcl.Checklist(
            id={"type": "input", "table": col.table.name, "column": col.name},
            options=[{"label": "True", "value": True}],
            value=checklist_value
        )
    elif tname in ("datetime", "timestamp", "date"):
        # DatePickerSingle expects `date` prop
        return dcl.DatePickerSingle(
            id={"type": "input", "table": col.table.name, "column": col.name},
            date=value
        )
    else:
        return dcl.Input(
            id={"type": "input", "table": col.table.name, "column": col.name},
            type="text", placeholder=f"{col.name} ({tname})", style={'width': '100%'},
            value=value
        )


def _create_link_dropdown(fields_list, conn, dbml, link_table, source_col, target_col, target_table, object_id=None, label_prefix=None):
    """Helper function to create and append a multi-select dropdown for a linked entity."""
    # ensure column names are strings
    if hasattr(source_col, "name"):
        source_col = source_col.name
    if hasattr(target_col, "name"):
        target_col = target_col.name

    options = get_dropdown_options(conn, target_table, dbml=dbml)
    if object_id is not None:
        options = [opt for opt in options if opt['value'] != object_id]

    cur = conn.cursor()
    cur.execute(f'SELECT "{target_col}" FROM "{link_table}" WHERE "{source_col}" = ? AND status != \'deleted\'', (object_id,))
    current_values = [row[0] for row in cur.fetchall()]

    label = label_prefix if label_prefix else f"Linked {target_table}"

    dropdown = dcc.Dropdown(
        id={"type": "link-input", "table": link_table, "source_col": source_col, "target_col": target_col},
        options=options,
        value=current_values,
        multi=True,
        placeholder=f"Select {label}...",
    )
    
    fields_list.append(html.Div([
        html.Label(label, style={"fontWeight": "bold"}),
        dropdown
    ], style={"marginBottom": "8px"}))


# ==============================================================
# FORM LAYOUT GENERATION
# ==============================================================

def generate_form_layout(table, object_id=None, dbml=None):
    """Generate a Dash form layout, including multi-select dropdowns for link tables."""
    fk_map = build_reference_index(dbml) if dbml else {}
    conn = db_connect()
    existing_data = get_latest_record(conn, table.name, object_id) if (conn and object_id) else {}

    fields = []
    for col in table.columns:
        comp = component_for_column(col, conn, fk_map, dbml=dbml, value=existing_data.get(col.name))
        fields.append(html.Div([
            html.Label(col.name, style={"fontWeight": "bold"}),
            comp
        ], style={"marginBottom": "8px"}))

    if dbml:
        link_tables = [t for t in dbml.tables if t.name not in NODE_TABLES]
        for link_table in link_tables:
            fks = [col for col in link_table.columns if (link_table.name, col.name) in fk_map]
            if len(fks) != 2:
                continue

            fk1_col, fk2_col = fks[0], fks[1]
            fk1_parent_name = fk_map[(link_table.name, fk1_col.name)][0]
            fk2_parent_name = fk_map[(link_table.name, fk2_col.name)][0]

            # Case 1: Self-referencing link table
            if fk1_parent_name == table.name and fk2_parent_name == table.name:
                p_col = fk1_col.name if 'parent' in fk1_col.name else fk2_col.name
                c_col = fk2_col.name if 'child' in fk2_col.name else fk1_col.name
                
                _create_link_dropdown(fields, conn, dbml, link_table.name, source_col=c_col, target_col=p_col,
                                     target_table=table.name, object_id=object_id, label_prefix="Parents")
                _create_link_dropdown(fields, conn, dbml, link_table.name, source_col=p_col, target_col=c_col,
                                     target_table=table.name, object_id=object_id, label_prefix="Children")

            # Case 2: Standard link table
            else:
                source_col, target_col, target_table = (None, None, None)
                if fk1_parent_name == table.name:
                    source_col, target_col, target_table = fk1_col.name, fk2_col.name, fk2_parent_name
                elif fk2_parent_name == table.name:
                    source_col, target_col, target_table = fk2_col.name, fk1_col.name, fk1_parent_name
                else:
                    continue
                
                _create_link_dropdown(fields, conn, dbml, link_table.name,
                                     source_col=source_col, target_col=target_col,
                                     target_table=target_table, object_id=object_id)
    
    conn.close()
    return html.Div([
        html.H3(f"Edit {table.name}" if object_id else f"Add {table.name}"),
        *fields,
        html.Button("Submit", id={"type": "submit", "table": table.name}, n_clicks=0),
        html.Div(id={"type": "output", "table": table.name})
    ])


# ==============================================================
# CALLBACK REGISTRATION
# ==============================================================

def register_callbacks(app, dbml):
    """Register one submit callback per table in the DBML schema."""
    for table in dbml.tables:
        input_ids = [{"type": "input", "table": table.name, "column": col.name} for col in table.columns]
        state_args = [State(i, "value") for i in input_ids]

        @app.callback(
            Output({"type": "output", "table": table.name}, "children"),
            Output('intermediary-loaded', 'data', allow_duplicate=True),
            Input({"type": "submit", "table": table.name}, "n_clicks"),
            State({"type": "link-input", "table": ALL, "source_col": ALL, "target_col": ALL}, "id"),
            State({"type": "link-input", "table": ALL, "source_col": ALL, "target_col": ALL}, "value"),
            State("current-person-id", "data"),
            *state_args,
            prevent_initial_call=True,
        )
        def handle_submit(n_clicks, link_ids, link_values, person_id, *values, _table=table):
            if n_clicks == 0:
                return None, no_update
            
            conn = db_connect()
            cur = conn.cursor()

            # Part 1: Handle the main object (Person, Initiative, etc.)
            columns = [col.name for col in _table.columns]
            data = dict(zip(columns, values))

            # Normalize Dash data types before SQL
            for k, v in data.items():
                if isinstance(v, list):
                    if len(v) == 0:
                        data[k] = False
                    elif len(v) == 1 and isinstance(v[0], bool):
                        data[k] = v[0]
                    else:
                        data[k] = ",".join(map(str, v))
                elif isinstance(v, bool):
                    data[k] = int(v)

            object_id = data.get('id')
            is_new_object = object_id is None
            
            out_msg = None
            if is_new_object:
                new_id = _get_max_id_from_cursor(cur, _table.name) + 1
                object_id = new_id
                data['id'] = new_id
                data['version'] = 1
                data['status'] = 'active'
                out_msg = html.Span(f"✅ Created {_table.name} record ID {data['id']}", style={"color": "green"})
            else:
                data['version'] = (data.get('version') or 0) + 1
                out_msg = html.Span(f"✅ Edited {_table.name} record ID {data['id']}", style={"color": "green"})
            
            data['timestamp'] = datetime.now().isoformat()
            data['created_by'] = person_id
            print(person_id)

            cols_sql = ", ".join([f'"{k}"' for k in data.keys()])
            placeholders = ", ".join(["?"] * len(data))
            vals = list(data.values())
            cur.execute(f'INSERT INTO "{_table.name}" ({cols_sql}) VALUES ({placeholders})', vals)

            # Part 2: Handle the Link Table Updates
            if not is_new_object and link_ids:
                for i, link_id_dict in enumerate(link_ids):
                    link_table = link_id_dict['table']
                    source_col = link_id_dict['source_col']
                    target_col = link_id_dict['target_col']
                    
                    newly_selected_ids = set(link_values[i] if link_values[i] else [])

                    cur.execute(f'SELECT id, "{target_col}" FROM "{link_table}" WHERE "{source_col}" = ? AND status != \'deleted\'', (object_id,))
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
                            'created_by': 1
                        }
                        if 'type' in [c.name for c in dbml.get_table(link_table).columns]:
                            insert_data['type'] = 'linked'

                        l_cols_sql = ", ".join([f'"{k}"' for k in insert_data.keys()])
                        l_placeholders = ", ".join(["?"] * len(insert_data))
                        cur.execute(f'INSERT INTO "{link_table}" ({l_cols_sql}) VALUES ({l_placeholders})', list(insert_data.values()))

            conn.commit()
            conn.close()

            return out_msg, datetime.now().isoformat()
