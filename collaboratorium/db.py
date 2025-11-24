import sqlite3
import os
from datetime import datetime, timezone
import json
import pandas as pd
import networkx as nx  # Import networkx for degree filtering


DB = 'database.db'


def db_connect():
    """Returns a new connection to the SQLite database."""
    return sqlite3.connect(DB)


def _now_utc_iso():
    """Returns the current time in UTC ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _dbml_to_sqlite_type(col_type: str) -> str:
    """Helper to map DBML data types to SQLite data types."""
    t = col_type.lower()
    if t in ('int', 'integer'):
        return 'INTEGER'
    if t == 'boolean':
        return 'INTEGER'  # SQLite uses 0/1 for booleans
    if t in ('datetime', 'date', 'timestamp'):
        return 'TEXT'
    # Default for varchar, text, char, string, etc.
    return 'TEXT'


def init_db(config):
    """
    Create the database schema dynamically from the config file.
    """
    existed = os.path.exists(DB)
    
    if existed:
        print("Database already exists. Skipping initialization.")
        return

    conn = db_connect()
    cur = conn.cursor()

    print("Initializing database schema from config YAML...")
    # Dynamically create tables from config
    for table_name, table in config["tables"].items():
        col_defs = []
        has_id = False
        has_version = False
        
        for col_name, col_type in table['fields'].items():
            # Use quotes to handle all table/column names
            col_defs.append(f'"{col_name}" {_dbml_to_sqlite_type(col_type)}')
            if col_name == 'id':
                has_id = True
            if col_name == 'version':
                has_version = True
        
        # Add composite primary key for versioned tables
        # Assumes tables with 'id' and 'version' are versioned
        if has_id and has_version:
            col_defs.append("PRIMARY KEY (id, version)")
        
        sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
        try:
            cur.execute(sql)
        except Exception as e:
            print(f"Failed to create table {table_name}: {e}\nSQL: {sql}")

    conn.commit()
    print("Database schema initialized.")
    
    conn.close()

# ----------------------------------------------------------------------
# RECORD RETRIEVAL
# ----------------------------------------------------------------------

def get_latest_record(table_name, object_id=None):
    """
    Get the latest (non-deleted) record from a versioned table.
    If object_id is provided, return the most recent version of that record.
    Otherwise return the latest record overall.
    """
    conn = db_connect()
    cur = conn.cursor()

    if object_id:
        cur.execute(
            f"""
            SELECT *
            FROM {table_name}
            WHERE id = ?
              AND (status IS NULL OR status != 'deleted')
            ORDER BY version DESC
            LIMIT 1
            """,
            (object_id,),
        )
    else:
        cur.execute(
            f"""
            SELECT *
            FROM {table_name}
            WHERE (status IS NULL OR status != 'deleted')
            ORDER BY timestamp DESC, version DESC
            LIMIT 1
            """
        )

    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    conn.close()
    return dict(zip(cols, row)) if row else {}


def get_all_records(table_name):
    """Return all current (non-deleted) records for a table."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM {table_name}
        WHERE (status IS NULL OR status != 'deleted')
        ORDER BY timestamp DESC, version DESC
        """
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_entry(form_name, forms_config, object_id):
    data = get_latest_record(forms_config[form_name]["default_table"], object_id)
    conn = db_connect()
    cur = conn.cursor()
    extra_elements = [element for element in forms_config[form_name]["elements"].keys() if element not in data.keys()]
    for element in extra_elements:

        if "store" in forms_config[form_name]["elements"][element].keys():
            link_table = forms_config[form_name]["elements"][element]["store"]["link_table"]
            source_col = forms_config[form_name]["elements"][element]["store"]['source_field']
            target_col = forms_config[form_name]["elements"][element]["store"]['target_field']

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
            data[element] = list(currently_linked_ids)
    conn.commit()
    conn.close()
    return data


def get_dropdown_options(table_name, value_column, label_column):
    """
    Fetch dropdown options for a foreign key reference.
    Shows 'name' column as label if present, otherwise uses ID.
    """
    conn = db_connect()
    cur = conn.cursor()


    try:
        sql_query = f'''
        WITH RankedRows AS (
            SELECT
                "{value_column}",
                "{label_column}",
                "status",
                -- 1. Rank all rows within each "{value_column}" group.
                --    The highest version gets rank (rn) = 1.
                ROW_NUMBER() OVER(PARTITION BY "{value_column}" ORDER BY "version" DESC) as rn
            FROM "{table_name}"
        )
        -- 2. From the ranked list, select only the top-ranked row (rn = 1)
        --    AND check its status.
        SELECT
            "{value_column}",
            "{label_column}"
        FROM RankedRows
        WHERE
            rn = 1 
            AND "status" != 'deleted'
        ORDER BY "{value_column}"
        '''
        cur.execute(sql_query)
        rows = cur.fetchall()
        return [{"label": str(r[1]), "value": r[0]} for r in rows]
    except Exception as e:
        print(f"[WARN] Error fetching options for {table_name}: {e}")
        return None


def build_elements_from_db(config,
                           include_deleted: bool = False,
                           node_types: list | None = None,
                           people_selected: list | None = None,
                           degree: int | None = None,
                           degree_types: list | None = None
                           ):
    """
    Build Cytoscape-style elements (nodes + edges) dynamically from the config.
    
    - include_deleted: Show items with 'deleted' status.
    - node_types: List of table names to show (e.g., ['people', 'initiatives']).
    - people_selected: List of people IDs (e.g., ['people-1']) to use as starting points.
    - degree: N-degree filtering from 'people_selected'. If None, shows all.
    """

    rconn = db_connect()

    def db_df(query):
        """Execute query, get latest version of each object, return DataFrame."""
        try:
            df = pd.read_sql_query(query, rconn)
        except Exception as e:
            print(f"[WARN] db_df query failed: {e}")
            return pd.DataFrame()
        if df.empty:
            return df
        # Get the latest version for each 'id'
        if 'id' in df.columns and 'version' in df.columns:
            df = df.sort_values(['id', 'version']).groupby('id', as_index=False).last()
        return df

    # Load ALL tables into dataframes. Filtering happens in memory.
    dataframes = {}
    for table in config["tables"].keys():
        dataframes[table] = db_df(f'SELECT * FROM "{table}"')

    # Apply status filter (exclude deleted) if requested
    def _filter_deleted(df):
        if df is None or df.empty:
            return df
        if include_deleted:
            return df
        if 'status' in df.columns:
            return df[df['status'].isna() | (df['status'] != 'deleted')]
        return df

    for name, df in dataframes.items():
        dataframes[name] = _filter_deleted(df)

    # --- 1. Build ALL Nodes ---
    
    def make_node(row, table_name):
        """Helper to create a Cytoscape node element."""
        nid = f"{table_name}-{int(row['id'])}"
        label = row.get('name') or row.get('Name') or row.get('email') or f"{table_name} {row.get('id')}"
        props = {k: v for k, v in row.items()}
        return {'data': {'id': nid, 'label': label, 'type': table_name, 'properties': props}, 'classes': table_name}

    all_nodes = []
    for table_name in config["node_tables"]:
        df = dataframes.get(table_name)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                try:
                    all_nodes.append(make_node(r, table_name))
                except Exception as e:
                    print(f"[WARN] Failed to create node for {table_name} row {r.get('id')}: {e}")
    
    # Set of all node IDs that were successfully created
    existing_node_ids = {n['data']['id'] for n in all_nodes}

    # --- 2. Build ALL Edges ---

    def add_edge(src_table, src_obj_id, tgt_table, tgt_obj_id, label, link_table=None, link_obj_id=None, link_status=None):
        """Helper to create a Cytoscape edge element."""
        try:
            if link_status == "deleted": return None
            if pd.isna(src_obj_id) or pd.isna(tgt_obj_id): return None
            
            src_id = f"{src_table}-{int(src_obj_id)}"
            tgt_id = f"{tgt_table}-{int(tgt_obj_id)}"
            
            # Don't add edges if the source/target node doesn't exist
            if src_id not in existing_node_ids or tgt_id not in existing_node_ids:
                return None
            if label == "created by":
                return None
                
            # Create a unique edge ID
            if link_table and link_obj_id is not None:
                edge_id = f"{link_table}-{int(link_obj_id)}"
            else:
                # Implied FK edge
                edge_id = f"fk-{src_id}-{tgt_id}"

            data = {
                'id': edge_id,
                'source': src_id,
                'target': tgt_id,
                'label': label,
                'status': link_status
            }
            
            # If this is an editable edge (from a link table), add its info
            if link_table and link_obj_id is not None:
                data['table_name'] = link_table
                data['object_id'] = int(link_obj_id)

            return {'data': data}
        except Exception as e:
            print(f"[WARN] Failed to add edge {label} ({src_obj_id} -> {tgt_obj_id}): {e}")
            return None

    all_edges = []
    link_tables = {table_name: table for table_name, table in config["tables"].items() if table_name not in config["node_tables"]}
    
    for (child_table, child_col_name), (parent_table, parent_col_name) in config.fk_map.items():
        try:
            # Case 1: Direct FK (e.g., initiatives.responsible_person -> people.id)
            if child_table in config["node_tables"]:
                df = dataframes.get(child_table)
                if df is None or df.empty: continue
                for _, row in df.iterrows():
                    if row.get(child_col_name) is not None and not pd.isna(row.get(child_col_name)):
                        edge = add_edge(
                            src_table=parent_table, # 'people'
                            src_obj_id=row[child_col_name],
                            tgt_table=child_table, # 'initiatives'
                            tgt_obj_id=row[parent_col_name], # 'id'
                            label=child_col_name.replace('_', ' ').replace('id', ''),
                            link_status=row.get('status')
                        )
                        if edge: all_edges.append(edge)
            
            # Case 2: Link Table (e.g., organisation_people_links)
            elif child_table in link_tables:
                # Find the *other* FK on this link table
                other_fk_col = None
                for (_table, col) in config.fk_map.keys():
                    if col != child_col_name and child_table == _table and (child_table, col) in config.fk_map:
                        other_fk_col = col
                        break
                
                if not other_fk_col: continue
                key_list = list(config.fk_map.keys())
                if key_list.index((child_table, child_col_name)) > key_list.index((child_table, other_fk_col)): continue # Process each link table only once

                other_parent_table_name = config.fk_map[(child_table, other_fk_col)][0]
                
                # Handle self-referencing tables
                if child_table == 'initiative_initiative_links':
                    source_col_name, target_col_name = 'parent_id', 'child_id'
                    source_table_name, target_table_name = 'initiatives', 'initiatives'
                else:
                    source_col_name, target_col_name = other_fk_col, child_col_name
                    source_table_name, target_table_name = other_parent_table_name, parent_table

                df = dataframes.get(child_table)
                if df is None or df.empty: continue
                
                for _, row in df.iterrows():
                    edge = add_edge(
                        src_table=source_table_name,
                        src_obj_id=row[source_col_name],
                        tgt_table=target_table_name,
                        tgt_obj_id=row[target_col_name],
                        label=row.get('type') or child_table.replace('_links', '').replace('_', ' '),
                        link_table=child_table,
                        link_obj_id=row.get('id'),
                        link_status=row.get('status')
                    )
                    if edge: all_edges.append(edge)
        except Exception as e:
            print(f"[WARN] Failed to build edge from ref {(child_table, child_col_name), (parent_table, parent_col_name)}: {e}")

    rconn.close()
    
    all_elements = all_nodes + all_edges

    # --- 3. Apply Degree Filter (if provided) ---
    
    final_elements = all_elements
    
    def custom_ego_graph(graph, queue, radius, degree_types):
        visited = set()
        # queue = [(ego_node, 0)]  # (node, distance)
        subgraph_nodes = set()

        while queue:
            current_node, current_distance = queue.pop(0)

            if current_node in visited or current_distance > radius:
                continue

            visited.add(current_node)
            subgraph_nodes.add(current_node)

            if graph.nodes[current_node].get("classes") in degree_types or current_distance == 0:
                for neighbor in graph.neighbors(current_node):
                    queue.append((neighbor, current_distance + 1))

        return graph.subgraph(subgraph_nodes)


    if people_selected and degree is not None:
        start_nodes = people_selected
        G = nx.Graph()
        for node in all_nodes:
            G.add_node(node['data']['id'], **node)
        for edge in all_edges:
            G.add_edge(edge['data']['source'], edge['data']['target'])

        nodes_to_keep = set()

        queue = [(node, 0) for node in start_nodes]

        neighbors_graph = custom_ego_graph(G, queue, radius=degree, degree_types=degree_types)
        nodes_to_keep.update(neighbors_graph.nodes())
        
        # Filter the elements based on the graph traversal
        nodes = [n for n in all_nodes if n['data']['id'] in nodes_to_keep]
        node_ids = {n['data']['id'] for n in nodes}
        edges = [e for e in all_edges if e['data']['source'] in node_ids and e['data']['target'] in node_ids]
        final_elements = nodes + edges

    # --- 4. Apply Node Type Filter (final step) ---
    
    if node_types:
        nodes = [e for e in final_elements if 'source' not in e['data'] and e['data']['type'] in node_types]
        node_ids = {n['data']['id'] for n in nodes}
        edges = [e for e in final_elements if 'source' in e['data'] and e['data']['source'] in node_ids and e['data']['target'] in node_ids]
        return nodes + edges
    else:
        # Return all elements (either degree-filtered or complete)
        return final_elements


# --- Utility Functions (unchanged) ---

def get_max_object_id(table_name: str):
    """Return the maximum object id (id column) for a table, or 0 if none."""
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT MAX(id) FROM "{table_name}"')
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    finally:
        conn.close()


def get_max_version(table_name: str, object_id: int):
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT MAX(version) FROM "{table_name}" WHERE id = ?', (object_id,))
        r = cur.fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    finally:
        conn.close()


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
