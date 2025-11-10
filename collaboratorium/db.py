import sqlite3
import os
from datetime import datetime, timezone
import json
import pandas as pd
from pydbml import PyDBML
import networkx as nx  # Import networkx for degree filtering
from visual_customization import NODE_TABLES


DB = 'database.db'
DBML_FILE = 'schema.dbml'

# Load the DBML schema once at the module level
try:
    with open(DBML_FILE) as f:
        dbml = PyDBML(f)
except FileNotFoundError:
    print(f"[ERROR] DBML file not found at {DBML_FILE}. Functions in db.py will fail.")
    dbml = None
except Exception as e:
    print(f"[ERROR] Failed to parse DBML file {DBML_FILE}: {e}")
    dbml = None


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


def init_db():
    """
    Create the database schema dynamically from the DBML file.
    Optionally seeds default data.
    """
    existed = os.path.exists(DB)
    
    if existed:
        print("Database already exists. Skipping initialization.")
        return

    if dbml is None:
        raise RuntimeError(f"DBML file not found or failed to parse at {DBML_FILE}. Cannot initialize DB.")

    conn = db_connect()
    cur = conn.cursor()

    print("Initializing database schema from DBML...")
    # Dynamically create tables from DBML
    for table in dbml.tables:
        col_defs = []
        has_id = False
        has_version = False
        
        for col in table.columns:
            # Use quotes to handle all table/column names
            col_defs.append(f'"{col.name}" {_dbml_to_sqlite_type(col.type)}')
            if col.name == 'id':
                has_id = True
            if col.name == 'version':
                has_version = True
        
        # Add composite primary key for versioned tables
        # Assumes tables with 'id' and 'version' are versioned
        if has_id and has_version:
            col_defs.append("PRIMARY KEY (id, version)")
        
        sql = f'CREATE TABLE IF NOT EXISTS "{table.name}" ({", ".join(col_defs)})'
        try:
            cur.execute(sql)
        except Exception as e:
            print(f"Failed to create table {table.name}: {e}\nSQL: {sql}")

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


def build_elements_from_db(include_deleted: bool = False, node_types: list | None = None, people_selected: list | None = None, degree: int = None):
    """
    Build Cytoscape-style elements (nodes + edges) dynamically from the DBML schema.
    
    - include_deleted: Show items with 'deleted' status.
    - node_types: List of table names to show (e.g., ['people', 'initiatives']).
    - people_selected: List of people IDs (e.g., ['people-1']) to use as starting points.
    - degree: N-degree filtering from 'people_selected'. If None, shows all.
    """
    if dbml is None:
        raise RuntimeError(f"DBML file not found or failed to parse. Cannot build elements.")

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

    # Build the FK map first for easy lookup
    fk_map = {}  # (child_table, child_col) -> (parent_table, parent_col)
    try:
        for ref in dbml.refs:
            col1 = ref.col1[0]
            col2 = ref.col2[0]
            child = (col1.table.name, col1.name)
            parent = (col2.table.name, col2.name)
            fk_map[child] = parent
    except Exception as e:
        print(f"[WARN] Could not build FK map: {e}")

    # Load ALL tables into dataframes. Filtering happens in memory.
    dataframes = {}
    for table in dbml.tables:
        dataframes[table.name] = db_df(f'SELECT * FROM "{table.name}"')

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
    for table_name in NODE_TABLES:
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
    link_tables = [t for t in dbml.tables if t.name not in NODE_TABLES]
    
    for ref in dbml.refs:
        try:
            child_table = ref.col1[0].table
            child_col_name = ref.col1[0].name
            parent_table = ref.col2[0].table
            parent_col_name = ref.col2[0].name # Usually 'id'

            # Case 1: Direct FK (e.g., initiatives.responsible_person -> people.id)
            if child_table.name in NODE_TABLES:
                df = dataframes.get(child_table.name)
                if df is None or df.empty: continue
                for _, row in df.iterrows():
                    if row.get(child_col_name) is not None and not pd.isna(row.get(child_col_name)):
                        edge = add_edge(
                            src_table=parent_table.name, # 'people'
                            src_obj_id=row[child_col_name],
                            tgt_table=child_table.name, # 'initiatives'
                            tgt_obj_id=row[parent_col_name], # 'id'
                            label=child_col_name.replace('_', ' ').replace('id', ''),
                            link_status=row.get('status')
                        )
                        if edge: all_edges.append(edge)
            
            # Case 2: Link Table (e.g., organisation_people_links)
            elif child_table in link_tables:
                # Find the *other* FK on this link table
                other_fk_col = None
                for col in child_table.columns:
                    if col.name != child_col_name and (child_table.name, col.name) in fk_map:
                        other_fk_col = col
                        break
                
                if not other_fk_col: continue
                if child_col_name > other_fk_col.name: continue # Process each link table only once

                other_parent_table_name = fk_map[(child_table.name, other_fk_col.name)][0]
                
                # Handle self-referencing tables
                if child_table.name == 'initiative_initiative_links':
                    source_col_name, target_col_name = 'parent_id', 'child_id'
                    source_table_name, target_table_name = 'initiatives', 'initiatives'
                else:
                    source_col_name, target_col_name = other_fk_col.name, child_col_name
                    source_table_name, target_table_name = other_parent_table_name, parent_table.name

                df = dataframes.get(child_table.name)
                if df is None or df.empty: continue
                
                for _, row in df.iterrows():
                    edge = add_edge(
                        src_table=source_table_name,
                        src_obj_id=row[source_col_name],
                        tgt_table=target_table_name,
                        tgt_obj_id=row[target_col_name],
                        label=row.get('type') or child_table.name.replace('_links', '').replace('_', ' '),
                        link_table=child_table.name,
                        link_obj_id=row.get('id'),
                        link_status=row.get('status')
                    )
                    if edge: all_edges.append(edge)
        except Exception as e:
            print(f"[WARN] Failed to build edge from ref {ref.col1[0].table.name}.{ref.col1[0].name}: {e}")

    rconn.close()
    
    all_elements = all_nodes + all_edges

    # --- 3. Apply Degree Filter (if provided) ---
    
    final_elements = all_elements
    
    if people_selected and degree is not None:
        G = nx.Graph()
        for node in all_nodes:
            G.add_node(node['data']['id'])
        for edge in all_edges:
            G.add_edge(edge['data']['source'], edge['data']['target'])

        nodes_to_keep = set()
        start_nodes = [pid for pid in people_selected if G.has_node(pid)]

        for start_node in start_nodes:
            # ego_graph finds all nodes within 'radius' (degree)
            neighbors_graph = nx.ego_graph(G, start_node, radius=degree)
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


# ----------------------------------------------------------------------
# INSERT / UPDATE
# ----------------------------------------------------------------------

def save_record_with_links(table_name, data, links=None):
    """
    Save a new or updated record. Versioned insert pattern:
    - If the record exists, increment version.
    - Otherwise start at version 1.
    - Update timestamp automatically.
    - Optionally update link tables (via links param).
    """

    conn = get_connection()
    cur = conn.cursor()

    record_id = data.get("id")
    now = datetime.now(timezone.utc).isoformat()

    # Fetch current version if exists
    if record_id:
        cur.execute(
            f"""
            SELECT version
            FROM {table_name}
            WHERE id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (record_id,),
        )
        row = cur.fetchone()
        next_version = (row["version"] + 1) if row else 1
    else:
        # If no ID, get max(id) + 1 or default to 1
        cur.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table_name}")
        record_id = cur.fetchone()[0]
        next_version = 1

    # Prepare record data
    data["id"] = record_id
    data["version"] = next_version
    data["timestamp"] = now

    # Build SQL
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    values = list(data.values())

    cur.execute(
        f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
        values,
    )

    # Handle link updates if provided
    if links:
        update_links(cur, table_name, record_id, links)

    conn.commit()
    conn.close()

    return record_id


# ----------------------------------------------------------------------
# LINK MANAGEMENT
# ----------------------------------------------------------------------

def update_links(cur, table_name, record_id, links):
    """
    Synchronize link tables for a record.
    Example of links param:
    {
      "activities_links": {
         "link_table": "activity_initiative_links",
         "source_field": "initiative_id",
         "target_field": "activity_id",
         "values": [1, 3, 5]
      }
    }
    """
    for link_field, link_def in links.items():
        link_table = link_def["link_table"]
        src_field = link_def["source_field"]
        tgt_field = link_def["target_field"]
        vals = link_def.get("values", [])

        # Delete existing links
        cur.execute(
            f"DELETE FROM {link_table} WHERE {src_field} = ?",
            (record_id,),
        )

        # Reinsert current ones
        for target_id in vals:
            cur.execute(
                f"""
                INSERT INTO {link_table} ({src_field}, {tgt_field}, status, timestamp)
                VALUES (?, ?, 'active', ?)
                """,
                (record_id, target_id, datetime.now(timezone.utc).isoformat()),
            )


# ----------------------------------------------------------------------
# DELETE / ARCHIVE
# ----------------------------------------------------------------------

def soft_delete_record(table_name, record_id):
    """Mark a record as deleted without removing it."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {table_name}
        SET status = 'deleted'
        WHERE id = ?
        """,
        (record_id,),
    )
    conn.commit()
    conn.close()
